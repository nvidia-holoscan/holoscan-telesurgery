/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "PolicyMapToDeltaQp.h"

#include <cuda_runtime_api.h>

#include <atomic>
#include <limits>
#include <new>

namespace nvcodec {
namespace cae {

namespace {

// Threads per launch block for the conversion kernel. One thread produces one output block.
constexpr unsigned int kConversionThreadsPerBlock = 128;

// Sentinel cell size meaning "scale-to-frame mapping" inside the shared cell arithmetic.
constexpr int32_t kFullFrameCell = 0;

// ConversionKernelParams::mappingKind values.
constexpr int32_t kMappingKindScaleToFrame = 0;
constexpr int32_t kMappingKindFixedCell = 1;

// Ceiling division for positive values, in 64-bit so the numerator cannot wrap.
constexpr uint64_t CeilDiv(uint64_t numer, uint64_t denom)
{
    return (numer + denom - 1) / denom;
}

// True when a * b would exceed the 64-bit range.
bool MulOverflows(uint64_t a, uint64_t b)
{
    return a != 0 && b > std::numeric_limits<uint64_t>::max() / a;
}

// True when a + b would exceed the 64-bit range.
bool AddOverflows(uint64_t a, uint64_t b)
{
    return b > std::numeric_limits<uint64_t>::max() - a;
}

Status MakeOk()
{
    return Status{};
}

Status MakeError(Error error, const char* message, CUresult cudaResult = CUDA_SUCCESS)
{
    Status status;
    status.error = error;
    status.cudaResult = cudaResult;
    status.message = message;
    return status;
}

// cudaError_t and CUresult are not a bijection, so the runtime code is named in the message
// rather than folded into Status::cudaResult. The fallback points at static storage too.
const char* FuncBySymbolMessage(cudaError_t err)
{
    switch (err)
    {
    case cudaErrorMemoryAllocation:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: out of memory";
    case cudaErrorInitializationError:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: CUDA is not initialized";
    case cudaErrorInsufficientDriver:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: driver too old for this"
               " toolkit";
    case cudaErrorNoDevice:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: no CUDA-capable device";
    case cudaErrorNoKernelImageForDevice:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: this build contains no"
               " image for the device's architecture";
    case cudaErrorInvalidDeviceFunction:
        return "cudaGetFuncBySymbol() for the conversion kernel failed: the kernel is not present"
               " in this build";
    default:
        break;
    }

    const char* name = cudaGetErrorName(err);
    return name != nullptr ? name : "cudaGetFuncBySymbol() for the conversion kernel failed";
}

}   // namespace

// Policy-map cell that owns pixel on one axis, under either spatial mapping. __host__ __device__
// so a host reference runs the same instructions as the kernel and cannot drift from it.
static __host__ __device__ inline int32_t CellOfPixel(int32_t pixel, int32_t mapExtent,
                                                      int32_t frameExtent, int32_t cellSizePixels)
{
    int32_t cell;
    if (cellSizePixels > 0)
    {
        cell = pixel / cellSizePixels;
    }
    else
    {
        const long long numer = (2LL * pixel + 1) * static_cast<long long>(mapExtent);
        const long long denom = 2LL * static_cast<long long>(frameExtent);
        cell = static_cast<int32_t>(numer / denom);
    }

    if (cell < 0)
    {
        cell = 0;
    }
    if (cell > mapExtent - 1)
    {
        cell = mapExtent - 1;
    }
    return cell;
}

// Last frame pixel, on one axis, that CellOfPixel() still maps to cell. The mapping is monotone,
// so each cell owns a contiguous run and the reduction can walk cells instead of pixels.
static __host__ __device__ inline int32_t LastPixelOfCell(int32_t cell, int32_t mapExtent,
                                                          int32_t frameExtent, int32_t cellSizePixels)
{
    if (cellSizePixels > 0)
    {
        const long long last =
            (static_cast<long long>(cell) + 1) * static_cast<long long>(cellSizePixels) - 1;
        const long long limit = static_cast<long long>(frameExtent) - 1;
        return static_cast<int32_t>((last < limit) ? last : limit);
    }

    const long long limit =
        ((static_cast<long long>(cell) + 1) * 2LL * static_cast<long long>(frameExtent) - 1)
        / static_cast<long long>(mapExtent);
    return static_cast<int32_t>((limit - 1) / 2);
}

// Integer rounding, so the reduction is bit-exactly reproducible on any device and on the host.
static __host__ __device__ inline int32_t RoundHalfAwayFromZero(long long numer, long long denom)
{
    if (denom <= 0)
    {
        return 0;
    }
    if (numer >= 0)
    {
        return static_cast<int32_t>((2LL * numer + denom) / (2LL * denom));
    }
    return -static_cast<int32_t>((-2LL * numer + denom) / (2LL * denom));
}

// A byte at or beyond kCaePolicyCount violates the input contract but is not undefined
// behaviour: it contributes a neutral 0 and is never used as an index.
static __host__ __device__ inline int32_t GetDeltaQpForPolicyId(uint8_t rawPolicyId,
                                                                const int32_t* deltaQpByPolicy)
{
    if (static_cast<uint32_t>(rawPolicyId) >= kCaePolicyCount)
    {
        return 0;
    }
    return deltaQpByPolicy[rawPolicyId];
}

// The reduction for one output block, shared verbatim by the kernel and any host reference. It
// is the equal-weight per-pixel mean PolicyMapToDeltaQp.h defines, evaluated in O(covered cells).
static __host__ __device__ inline int8_t ComputeBlockDeltaQp(
    int32_t bx, int32_t by,
    const uint8_t* policyMap, uint64_t policyPitch,
    const int32_t* deltaQpByPolicy,
    int32_t frameW, int32_t frameH,
    int32_t mapW, int32_t mapH,
    int32_t cellW, int32_t cellH,
    int32_t blockW, int32_t blockH)
{
    // The last block of a row or column is partial when the frame is not a multiple of the block.
    const int32_t xBegin = bx * blockW;
    const int32_t yBegin = by * blockH;
    const int32_t xEnd = (xBegin + blockW < frameW) ? (xBegin + blockW) : frameW;
    const int32_t yEnd = (yBegin + blockH < frameH) ? (yBegin + blockH) : frameH;

    long long numer = 0;

    int32_t py = yBegin;
    while (py < yEnd)
    {
        const int32_t cy = CellOfPixel(py, mapH, frameH, cellH);
        int32_t pyLast = LastPixelOfCell(cy, mapH, frameH, cellH);
        if (pyLast > yEnd - 1)
        {
            pyLast = yEnd - 1;
        }
        if (pyLast < py)
        {
            // Unreachable for a cell an in-frame pixel maps to; guarantees forward progress.
            pyLast = py;
        }
        const int32_t rows = pyLast - py + 1;

        const uint8_t* const cellRow = policyMap + static_cast<uint64_t>(cy) * policyPitch;

        int32_t px = xBegin;
        while (px < xEnd)
        {
            const int32_t cx = CellOfPixel(px, mapW, frameW, cellW);
            int32_t pxLast = LastPixelOfCell(cx, mapW, frameW, cellW);
            if (pxLast > xEnd - 1)
            {
                pxLast = xEnd - 1;
            }
            if (pxLast < px)
            {
                pxLast = px;
            }
            const int32_t cols = pxLast - px + 1;

            const int32_t delta = GetDeltaQpForPolicyId(cellRow[cx], deltaQpByPolicy);
            numer += static_cast<long long>(delta) * static_cast<long long>(rows) *
                     static_cast<long long>(cols);

            px = pxLast + 1;
        }

        py = pyLast + 1;
    }

    const long long denom =
        static_cast<long long>(xEnd - xBegin) * static_cast<long long>(yEnd - yBegin);
    return static_cast<int8_t>(RoundHalfAwayFromZero(numer, denom));
}

namespace {

// Everything one conversion needs, flattened from the two views plus the profile. Stack-local
// per call: the five deltas travel by value, so there is no device lookup table to keep coherent.
struct ConversionKernelParams
{
    const uint8_t* policyMap{};
    uint64_t policyPitchBytes{};

    int8_t* deltaQpMap{};
    uint64_t deltaQpPitchBytes{};

    int32_t deltaQpByPolicy[kCaePolicyCount]{};

    int32_t frameW{};
    int32_t frameH{};
    int32_t policyMapW{};
    int32_t policyMapH{};
    int32_t fixedCellW{};
    int32_t fixedCellH{};
    int32_t blockW{};
    int32_t blockH{};
    int32_t gridW{};
    int32_t gridH{};
    int32_t mappingKind{};
};

// One thread per output block. Writes exactly the [0, gridH) x [0, gridW) sub-rectangle and
// never the padding, which is why the owner zero-fills the whole allocation once before first use.
__global__ void ConvertPolicyMapToDeltaQpKernel(ConversionKernelParams p)
{
    const uint64_t index = static_cast<uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const uint64_t nBlocks = static_cast<uint64_t>(p.gridW) * static_cast<uint64_t>(p.gridH);
    if (index >= nBlocks)
    {
        return;
    }

    const int32_t bx = static_cast<int32_t>(index % static_cast<uint64_t>(p.gridW));
    const int32_t by = static_cast<int32_t>(index / static_cast<uint64_t>(p.gridW));

    // mappingKind is the authoritative discriminator; the sentinel-zero cell size is how the
    // shared arithmetic spells "scale to frame".
    const int32_t cellW = (p.mappingKind == kMappingKindFixedCell) ? p.fixedCellW : kFullFrameCell;
    const int32_t cellH = (p.mappingKind == kMappingKindFixedCell) ? p.fixedCellH : kFullFrameCell;

    const int8_t value = ComputeBlockDeltaQp(bx, by, p.policyMap, p.policyPitchBytes,
                                             p.deltaQpByPolicy, p.frameW, p.frameH, p.policyMapW,
                                             p.policyMapH, cellW, cellH, p.blockW, p.blockH);

    p.deltaQpMap[static_cast<uint64_t>(by) * p.deltaQpPitchBytes + static_cast<uint64_t>(bx)] =
        value;
}

// True when both axes are in [1, kMaxDimension], the range every uint32 to int32 cast assumes.
bool ExtentInRange(Extent2D extent)
{
    return extent.width >= 1 && extent.width <= kMaxDimension &&
           extent.height >= 1 && extent.height <= kMaxDimension;
}

// Bytes a pitched rectangle really touches: every full row plus the active part of the last one.
// Checked in 64-bit, because a caller-supplied pitch can be any value at all.
Status RequiredSpanBytes(uint64_t rowCount, uint64_t rowPitchBytes, uint64_t rowBytes,
                         uint64_t& outSpan)
{
    if (MulOverflows(rowCount - 1, rowPitchBytes))
    {
        return MakeError(Error::InvalidArgument, "row pitch times row count overflows 64 bits");
    }
    const uint64_t base = (rowCount - 1) * rowPitchBytes;
    if (AddOverflows(base, rowBytes))
    {
        return MakeError(Error::InvalidArgument, "required buffer span overflows 64 bits");
    }
    outSpan = base + rowBytes;
    return MakeOk();
}

// The source descriptor on its own terms. The spatial relationship between the two views is
// checked separately, once the destination's frame size has been validated as well.
Status ValidatePolicyMapView(const PolicyMapView& view, uint64_t& outSpan)
{
    if (view.devicePtr == 0)
    {
        return MakeError(Error::InvalidArgument, "PolicyMapView::devicePtr must be non-null");
    }
    if (!ExtentInRange(view.mapSizeCells))
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapView::mapSizeCells extents must be in [1, kMaxDimension]");
    }
    if (view.rowPitchBytes < static_cast<uint64_t>(view.mapSizeCells.width))
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapView::rowPitchBytes is below the policy-map row width");
    }
    if (!view.spatialMapping.has_value())
    {
        // No implicit default: an omitted registration that silently became scale-to-frame would
        // produce a plausible map pointing at the wrong content.
        return MakeError(Error::InvalidArgument,
                         "PolicyMapView::spatialMapping must contain a value; there is no default "
                         "registration");
    }

    const Status spanStatus = RequiredSpanBytes(view.mapSizeCells.height, view.rowPitchBytes,
                                                view.mapSizeCells.width, outSpan);
    if (!spanStatus.IsOk())
    {
        return spanStatus;
    }
    if (view.capacityBytes < outSpan)
    {
        return MakeError(Error::BufferTooSmall,
                         "PolicyMapView::capacityBytes is below the span its own geometry requires");
    }

    return MakeOk();
}

// The destination descriptor, including its agreement with the session profile. Self-consistency
// is checkable and is checked; whether a claimed frame size is a real session's is not.
Status ValidateDeltaQpMapView(const DeltaQpMapView& view, Extent2D profileBlockSizePixels,
                              uint64_t& outSpan)
{
    if (view.devicePtr == 0)
    {
        return MakeError(Error::InvalidArgument, "DeltaQpMapView::devicePtr must be non-null");
    }
    if (!ExtentInRange(view.frameSizePixels))
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::frameSizePixels extents must be in [1, kMaxDimension]");
    }
    if (!ExtentInRange(view.blockSizePixels))
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::blockSizePixels extents must be in [1, kMaxDimension]");
    }
    if (!ExtentInRange(view.mapSizeBlocks))
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::mapSizeBlocks extents must be in [1, kMaxDimension]");
    }

    // A 16x16 view submitted to an AV1 session would write a plausible map for the wrong grid.
    if (view.blockSizePixels.width != profileBlockSizePixels.width ||
        view.blockSizePixels.height != profileBlockSizePixels.height)
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::blockSizePixels does not equal the session profile's "
                         "block footprint");
    }

    // Exact equality, not ">=": a spare block row would never be written, and a short one would
    // be addressed outside the caller's active rectangle.
    if (static_cast<uint64_t>(view.mapSizeBlocks.width) !=
            CeilDiv(view.frameSizePixels.width, view.blockSizePixels.width) ||
        static_cast<uint64_t>(view.mapSizeBlocks.height) !=
            CeilDiv(view.frameSizePixels.height, view.blockSizePixels.height))
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::mapSizeBlocks must equal "
                         "ceil(frameSizePixels / blockSizePixels)");
    }

    if (view.rowPitchBytes < static_cast<uint64_t>(view.mapSizeBlocks.width))
    {
        return MakeError(Error::InvalidArgument,
                         "DeltaQpMapView::rowPitchBytes is below the delta-QP grid width");
    }

    const Status spanStatus = RequiredSpanBytes(view.mapSizeBlocks.height, view.rowPitchBytes,
                                                view.mapSizeBlocks.width, outSpan);
    if (!spanStatus.IsOk())
    {
        return spanStatus;
    }
    if (view.capacityBytes < outSpan)
    {
        return MakeError(Error::BufferTooSmall,
                         "DeltaQpMapView::capacityBytes is below the span its own geometry "
                         "requires");
    }

    return MakeOk();
}

// Fixed-cell coverage is checked against this call's destination frame, which is the only frame
// size the converter knows - it holds none of its own.
Status ValidateAndFlattenSpatialMapping(const SpatialMapping& mapping, Extent2D mapSizeCells,
                                        Extent2D frameSizePixels, int32_t& outMappingKind,
                                        int32_t& outCellW, int32_t& outCellH)
{
    if (const auto* fixed = std::get_if<FixedCellMapping>(&mapping))
    {
        const Extent2D cell = fixed->cellSizePixels;
        if (!ExtentInRange(cell))
        {
            return MakeError(Error::InvalidArgument,
                             "FixedCellMapping::cellSizePixels extents must be in "
                             "[1, kMaxDimension]");
        }

        // Exact coverage, not ">=": a spare map row would be silently ignored, which is a typo.
        if (CeilDiv(frameSizePixels.width, cell.width) != mapSizeCells.width ||
            CeilDiv(frameSizePixels.height, cell.height) != mapSizeCells.height)
        {
            return MakeError(Error::InvalidArgument,
                             "FixedCellMapping does not exactly cover this call's destination "
                             "frame: mapSizeCells must equal ceil(frameSizePixels / cellSizePixels)");
        }

        outMappingKind = kMappingKindFixedCell;
        outCellW = static_cast<int32_t>(cell.width);
        outCellH = static_cast<int32_t>(cell.height);
        return MakeOk();
    }

    // ScaleToFrameMapping accepts any valid nonzero source extent, including one larger than the
    // frame: the pixel-centre rule handles remainders and cells that own no pixel centre at all.
    outMappingKind = kMappingKindScaleToFrame;
    outCellW = kFullFrameCell;
    outCellH = kFullFrameCell;
    return MakeOk();
}

// The source's read span against the destination's full declared capacity, because nothing bounds
// NVENC's read extent. Strict inequalities keep adjacent, disjoint suballocations legal.
Status ValidateNoOverlap(CUdeviceptr policyPtr, uint64_t policySpan, CUdeviceptr deltaQpPtr,
                         uint64_t deltaQpCapacity)
{
    const uint64_t policyBegin = static_cast<uint64_t>(policyPtr);
    const uint64_t deltaQpBegin = static_cast<uint64_t>(deltaQpPtr);

    if (AddOverflows(policyBegin, policySpan) || AddOverflows(deltaQpBegin, deltaQpCapacity))
    {
        return MakeError(Error::InvalidArgument,
                         "a view's device address plus its span wraps the 64-bit address space");
    }

    if (policyBegin < deltaQpBegin + deltaQpCapacity && deltaQpBegin < policyBegin + policySpan)
    {
        return MakeError(Error::InvalidArgument,
                         "the policy map's read span overlaps the delta-QP map's declared "
                         "allocation");
    }

    return MakeOk();
}

// A second transcription of the profile's invariants, independent of the factory's own check, so
// a defect has to appear in both places to reach a launch. Structure only, never the numbers.
Status ValidateProfileValues(uint8_t profileKind, const int8_t (&deltaQpByPolicy)[kCaePolicyCount],
                             Extent2D blockSizePixels, int8_t minDeltaQp, int8_t maxDeltaQp)
{
    // IsValid() only asks whether the kind is non-zero, which leaves every other byte accepted.
    // The approved set is H.264, HEVC and AV1 - kinds 1, 2 and 3 - spelled out, not looked up.
    if (profileKind < 1u || profileKind > 3u)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile names no approved codec; the profile kind must be "
                         "one of the three the encoder authors");
    }
    if (!ExtentInRange(blockSizePixels))
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile block extents must be in [1, kMaxDimension]");
    }
    if (minDeltaQp > 0 || maxDeltaQp < 0)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires minDeltaQp <= 0 <= maxDeltaQp");
    }
    if (deltaQpByPolicy[static_cast<size_t>(CaePolicyId::Neutral)] != 0)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires CaePolicyId::Neutral to resolve to "
                         "exactly 0");
    }
    if (!(deltaQpByPolicy[static_cast<size_t>(CaePolicyId::ProtectStrong)] <
              deltaQpByPolicy[static_cast<size_t>(CaePolicyId::Protect)] &&
          deltaQpByPolicy[static_cast<size_t>(CaePolicyId::Protect)] < 0 &&
          0 < deltaQpByPolicy[static_cast<size_t>(CaePolicyId::Deprioritize)] &&
          deltaQpByPolicy[static_cast<size_t>(CaePolicyId::Deprioritize)] <
              deltaQpByPolicy[static_cast<size_t>(CaePolicyId::DeprioritizeStrong)]))
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires protectStrong < protect < 0 < "
                         "deprioritize < deprioritizeStrong");
    }
    for (size_t i = 0; i < kCaePolicyCount; ++i)
    {
        if (deltaQpByPolicy[i] < minDeltaQp || deltaQpByPolicy[i] > maxDeltaQp)
        {
            return MakeError(Error::InvalidArgument,
                             "PolicyToDeltaQpProfile entry lies outside the codec's legal delta "
                             "range");
        }
    }

    return MakeOk();
}

}   // namespace

// Session-level facts only. A buffer pointer, geometry, buffer count or pool index here would
// reintroduce the initialization-time source/destination pairing the per-frame call exists to drop.
struct PolicyMapToDeltaQpConverter::Impl
{
    CUstream conversionStream = nullptr;    // borrowed; neither created nor destroyed here
    CUcontext context = nullptr;            // derived from the stream, so the two cannot disagree
    CUfunction kernel = nullptr;            // resolved once, so the hot path has nothing to look up
    PolicyToDeltaQpProfile profile{};       // immutable session token, copied into every launch

    // Set when a submission failed after the source-event wait was accepted, which is not
    // undoable. Atomic because teardown may read it from a thread other than the one that set it.
    std::atomic<bool> submissionPoisoned{false};
};

const char* ToString(Error error) noexcept
{
    switch (error)
    {
    case Error::Success:                 return "Success";
    case Error::InvalidArgument:         return "InvalidArgument";
    case Error::Unsupported:             return "Unsupported";
    case Error::BufferTooSmall:          return "BufferTooSmall";
    case Error::ContextMismatch:         return "ContextMismatch";
    case Error::OutOfMemory:             return "OutOfMemory";
    case Error::CudaError:               return "CudaError";
    case Error::SubmissionIndeterminate: return "SubmissionIndeterminate";
    }
    return "Unknown";
}

// The special members are defined here, not in the header, because Impl is incomplete there.
PolicyMapToDeltaQpConverter::PolicyMapToDeltaQpConverter() noexcept = default;
PolicyMapToDeltaQpConverter::PolicyMapToDeltaQpConverter(PolicyMapToDeltaQpConverter&&) noexcept =
    default;

PolicyMapToDeltaQpConverter::~PolicyMapToDeltaQpConverter() noexcept = default;

bool PolicyMapToDeltaQpConverter::IsValid() const noexcept
{
    return impl_ != nullptr;
}

Status PolicyMapToDeltaQpConverter::Create(CUstream conversionStream,
                                           const PolicyToDeltaQpProfile& policyToDeltaQpProfile,
                                           PolicyMapToDeltaQpConverter* out) noexcept
{
    if (out == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapToDeltaQpConverter::Create() requires a non-null out");
    }
    if (out->impl_ != nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapToDeltaQpConverter::Create() requires an empty out; it never "
                         "overwrites one");
    }

    // The legacy and per-thread default streams carry implicit ordering against unrelated work.
    // They are spelled as small integer handles, hence the numeric comparison.
    if (conversionStream == nullptr || conversionStream == CU_STREAM_LEGACY ||
        conversionStream == CU_STREAM_PER_THREAD)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapToDeltaQpConverter::Create() requires an explicit conversion "
                         "stream, not NULL/legacy/per-thread");
    }

    unsigned int streamFlags = 0;
    CUresult res = cuStreamGetFlags(conversionStream, &streamFlags);
    if (res != CUDA_SUCCESS)
    {
        return MakeError(Error::CudaError, "cuStreamGetFlags() failed on the conversion stream",
                         res);
    }
    if ((streamFlags & CU_STREAM_NON_BLOCKING) == 0)
    {
        return MakeError(Error::InvalidArgument,
                         "the conversion stream must be created with CU_STREAM_NON_BLOCKING");
    }

    // Deriving the context from the stream removes any way for the two to disagree.
    CUcontext streamCtx = nullptr;
    res = cuStreamGetCtx(conversionStream, &streamCtx);
    if (res != CUDA_SUCCESS)
    {
        return MakeError(Error::CudaError, "cuStreamGetCtx() failed on the conversion stream", res);
    }

    CUcontext currentCtx = nullptr;
    res = cuCtxGetCurrent(&currentCtx);
    if (res != CUDA_SUCCESS)
    {
        return MakeError(Error::CudaError, "cuCtxGetCurrent() failed", res);
    }
    if (currentCtx == nullptr || currentCtx != streamCtx)
    {
        return MakeError(Error::ContextMismatch,
                         "the conversion stream's context must be current in the calling thread");
    }

    if (!policyToDeltaQpProfile.IsValid())
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyMapToDeltaQpConverter::Create() requires a valid "
                         "PolicyToDeltaQpProfile resolved from the encoder session's codec GUID");
    }

    // The converter is a friend of the token, so it reads the resolved values directly.
    const Status profileStatus = ValidateProfileValues(policyToDeltaQpProfile.profileKind_,
                                                       policyToDeltaQpProfile.deltaQpByPolicy_,
                                                       policyToDeltaQpProfile.blockSizePixels_,
                                                       policyToDeltaQpProfile.minDeltaQp_,
                                                       policyToDeltaQpProfile.maxDeltaQp_);
    if (!profileStatus.IsOk())
    {
        return profileStatus;
    }

    std::unique_ptr<Impl> impl;
    try
    {
        impl = std::make_unique<Impl>();
    }
    catch (const std::bad_alloc&)
    {
        return MakeError(Error::OutOfMemory, "failed to allocate the converter");
    }

    impl->conversionStream = conversionStream;
    impl->context = streamCtx;
    impl->profile = policyToDeltaQpProfile;

    cudaFunction_t function = nullptr;
    const cudaError_t funcErr =
        cudaGetFuncBySymbol(&function, reinterpret_cast<const void*>(ConvertPolicyMapToDeltaQpKernel));
    if (funcErr != cudaSuccess || function == nullptr)
    {
        // Report what the runtime said and leave Status::cudaResult at CUDA_SUCCESS: inventing a
        // CUresult would misdiagnose an out-of-memory or an old driver as a missing kernel.
        const Error category = (funcErr == cudaErrorMemoryAllocation) ? Error::OutOfMemory
                                                                     : Error::CudaError;
        return MakeError(category, FuncBySymbolMessage(funcErr));
    }
    impl->kernel = function;

    out->impl_ = std::move(impl);
    return MakeOk();
}

Status PolicyMapToDeltaQpConverter::ConvertAsync(const PolicyMapView& policyMapView,
                                                 const DeltaQpWriteTarget& deltaQpWriteTarget,
                                                 CUevent policyMapReadyEvent) const noexcept
{
    return ConvertAsync(policyMapView, deltaQpWriteTarget.view, policyMapReadyEvent,
                        deltaQpWriteTarget.completionEvent);
}

Status PolicyMapToDeltaQpConverter::ConvertAsync(const PolicyMapView& policyMapView,
                                                 const DeltaQpMapView& deltaQpMapView,
                                                 CUevent policyMapReadyEvent,
                                                 CUevent deltaQpMapReadyEvent) const noexcept
{
    // Everything that can fail happens before the first enqueue. The recorded context must be
    // current on this thread; that is a caller precondition and is deliberately not queried.
    if (!impl_)
    {
        return MakeError(Error::InvalidArgument,
                         "ConvertAsync() called on an invalid converter");
    }
    if (impl_->submissionPoisoned.load(std::memory_order_relaxed))
    {
        // Nothing is queued by this call, so the caller may return both of these resources
        // unused; the ones the original indeterminate submission quarantined stay quarantined.
        return MakeError(Error::InvalidArgument,
                         "ConvertAsync() called on a converter poisoned by an earlier "
                         "indeterminate submission; no work was queued");
    }

    if (policyMapReadyEvent == nullptr || deltaQpMapReadyEvent == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "ConvertAsync() requires non-null policyMapReadyEvent and "
                         "deltaQpMapReadyEvent");
    }
    if (policyMapReadyEvent == deltaQpMapReadyEvent)
    {
        // One event cannot both order the producer before the kernel and signal the kernel's
        // completion: the wait would be satisfied by the record this call is about to make.
        return MakeError(Error::InvalidArgument,
                         "ConvertAsync() requires policyMapReadyEvent and deltaQpMapReadyEvent to "
                         "be distinct events");
    }

    uint64_t policySpan = 0;
    Status status = ValidatePolicyMapView(policyMapView, policySpan);
    if (!status.IsOk())
    {
        return status;
    }

    uint64_t deltaQpSpan = 0;
    status = ValidateDeltaQpMapView(deltaQpMapView, impl_->profile.blockSizePixels_, deltaQpSpan);
    if (!status.IsOk())
    {
        return status;
    }

    int32_t mappingKind = kMappingKindScaleToFrame;
    int32_t cellW = kFullFrameCell;
    int32_t cellH = kFullFrameCell;
    status = ValidateAndFlattenSpatialMapping(*policyMapView.spatialMapping,
                                              policyMapView.mapSizeCells,
                                              deltaQpMapView.frameSizePixels, mappingKind, cellW,
                                              cellH);
    if (!status.IsOk())
    {
        return status;
    }

    status = ValidateNoOverlap(policyMapView.devicePtr, policySpan, deltaQpMapView.devicePtr,
                               deltaQpMapView.capacityBytes);
    if (!status.IsOk())
    {
        return status;
    }

    // Stack-local; nothing here is retained.
    ConversionKernelParams params{};
    params.policyMap = reinterpret_cast<const uint8_t*>(policyMapView.devicePtr);
    params.policyPitchBytes = policyMapView.rowPitchBytes;
    params.deltaQpMap = reinterpret_cast<int8_t*>(deltaQpMapView.devicePtr);
    params.deltaQpPitchBytes = deltaQpMapView.rowPitchBytes;

    for (size_t i = 0; i < kCaePolicyCount; ++i)
    {
        params.deltaQpByPolicy[i] = static_cast<int32_t>(impl_->profile.deltaQpByPolicy_[i]);
    }

    params.frameW = static_cast<int32_t>(deltaQpMapView.frameSizePixels.width);
    params.frameH = static_cast<int32_t>(deltaQpMapView.frameSizePixels.height);
    params.policyMapW = static_cast<int32_t>(policyMapView.mapSizeCells.width);
    params.policyMapH = static_cast<int32_t>(policyMapView.mapSizeCells.height);
    params.fixedCellW = cellW;
    params.fixedCellH = cellH;
    params.blockW = static_cast<int32_t>(deltaQpMapView.blockSizePixels.width);
    params.blockH = static_cast<int32_t>(deltaQpMapView.blockSizePixels.height);
    params.gridW = static_cast<int32_t>(deltaQpMapView.mapSizeBlocks.width);
    params.gridH = static_cast<int32_t>(deltaQpMapView.mapSizeBlocks.height);
    params.mappingKind = mappingKind;

    const uint64_t nBlocks = static_cast<uint64_t>(params.gridW) * static_cast<uint64_t>(params.gridH);
    const unsigned int launchBlocks =
        static_cast<unsigned int>(CeilDiv(nBlocks, kConversionThreadsPerBlock));

    // Enqueue wait, launch, record, and nothing else. Error handling stops being transactional
    // after the wait is accepted; see Error::SubmissionIndeterminate.
    CUresult res = cuStreamWaitEvent(impl_->conversionStream, policyMapReadyEvent, 0);
    if (res != CUDA_SUCCESS)
    {
        // Nothing was queued: the caller may drain its producer write and reuse both resources.
        return MakeError(Error::CudaError,
                         "cuStreamWaitEvent() failed on policyMapReadyEvent; no conversion kernel "
                         "was queued",
                         res);
    }

    void* args[] = {&params};
    res = cuLaunchKernel(impl_->kernel,
                         launchBlocks, 1, 1,
                         kConversionThreadsPerBlock, 1, 1,
                         0, impl_->conversionStream, args, nullptr);
    if (res != CUDA_SUCCESS)
    {
        impl_->submissionPoisoned.store(true, std::memory_order_relaxed);
        return MakeError(Error::SubmissionIndeterminate,
                         "cuLaunchKernel() failed after the source-event wait was accepted; the "
                         "stream carries a wait with no completion record",
                         res);
    }

    res = cuEventRecord(deltaQpMapReadyEvent, impl_->conversionStream);
    if (res != CUDA_SUCCESS)
    {
        impl_->submissionPoisoned.store(true, std::memory_order_relaxed);
        return MakeError(Error::SubmissionIndeterminate,
                         "cuEventRecord() failed on deltaQpMapReadyEvent; the conversion kernel may "
                         "still be writing the destination with no valid completion signal",
                         res);
    }

    return MakeOk();
}

}   // namespace cae
}   // namespace nvcodec
