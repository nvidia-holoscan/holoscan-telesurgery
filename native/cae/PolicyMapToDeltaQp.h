/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <cuda.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <variant>

namespace nvcodec {
namespace cae {

/**
*  @brief Failure categories returned by this interface.
*  Read Status::error first, then Status::cudaResult, then Status::message.
*/
enum class Error
{
    Success,
    InvalidArgument,    /**< A null pointer, or an argument outside its documented range. */
    Unsupported,        /**< A well-formed request this sample does not implement. */
    BufferTooSmall,     /**< A view's capacity cannot hold the geometry that view declares. */
    ContextMismatch,    /**< A stream's context is not the calling thread's current context. */
    OutOfMemory,        /**< A host or CUDA-runtime allocation failed during setup. */
    CudaError,          /**< Any other CUDA failure; see Status::cudaResult, then the message. */

    /**
    *  @brief A launch or a record failed after the source wait had been accepted, so the
    *  submission is partly enqueued and completion is unproven. It poisons the converter
    *  against further submissions. Never retry that frame: quarantine both buffers and both
    *  events, and treat neither source reuse nor source destruction as safe until checked
    *  conversion-stream quiescence has succeeded.
    */
    SubmissionIndeterminate
};

/**
*  @brief Result of a call. message points at static storage - a string literal, or the CUDA
*  runtime's own error name - so no failure path allocates. cudaResult is meaningful only when
*  a driver call failed; a CUDA runtime failure leaves it CUDA_SUCCESS and names the runtime
*  error in message instead of fabricating a CUresult the driver never returned.
*/
struct Status
{
    Error error{Error::Success};
    CUresult cudaResult{CUDA_SUCCESS};
    const char* message{""};

    [[nodiscard]] bool IsOk() const noexcept
    {
        return error == Error::Success;
    }
};

/**
*  @brief Human-readable name of error, for logging. Never null.
*/
const char* ToString(Error error) noexcept;

namespace detail {

/**
*  @brief The raw-value profile factory, defined where the normative tables are and named here
*  only so PolicyToDeltaQpProfile can befriend it. The raw signed deltas are what this interface
*  exists not to have applications choose.
*/
class PolicyToDeltaQpProfileFactory;

}   // namespace detail

/**
*  @brief A width/height pair in whatever unit the containing field documents.
*/
struct Extent2D
{
    uint32_t width{};
    uint32_t height{};
};

/**
*  @brief The complete policy map spans the complete encoded frame proportionally, which is the
*  registration a producer that resamples the whole frame uniformly emits. Cell footprints are
*  equal only when the map divides the frame exactly; an uneven ratio makes them differ by one
*  pixel, and a map axis larger than the frame axis leaves some cells owning no pixel centre at
*  all. Both follow from the pixel-centre rule at the end of this header and are not errors.
*/
struct ScaleToFrameMapping
{
};

/**
*  @brief Policy cell (x, y) covers the luma region starting at (x * cellSizePixels.width,
*  y * cellSizePixels.height), clipped to the frame, which is what a producer that walks the
*  frame in fixed-size blocks emits. The final cell on each axis may be partial. Every call
*  requires mapSizeCells to equal ceil(frameSizePixels / cellSizePixels) on both axes; a spare
*  map row or column would be silently ignored, so it is rejected instead.
*/
struct FixedCellMapping
{
    Extent2D cellSizePixels{};
};

/**
*  @brief Tagged union of the two supported spatial mappings. Neither variant expresses a crop
*  origin, a pad offset, an arbitrary affine transform or a letterbox rectangle, so a producer
*  must undo those effects and supply a map already registered to the full encoded frame. An
*  offset crop is not silently treated as either variant.
*/
using SpatialMapping = std::variant<ScaleToFrameMapping, FixedCellMapping>;

/**
*  @brief One qualitative encoding request per policy-map cell, stored as a plain byte. Protect
*  asks for lower local quantization and Deprioritize for higher; the strong forms ask for more
*  of the same. Every profile resolves them so that protectStrong < protect < 0 == neutral <
*  deprioritize < deprioritizeStrong. That ordering holds only within one resolved codec
*  profile: no bitrate, PSNR or cross-codec equivalence is promised. Neutral is zero so that a
*  zero-filled allocation is a valid, fully neutral map.
*/
enum class CaePolicyId : uint8_t
{
    Neutral             = 0,
    Protect             = 1,
    ProtectStrong       = 2,
    Deprioritize        = 3,
    DeprioritizeStrong  = 4
};

/** Number of policies, and therefore the first byte value that is not a valid policy. */
inline constexpr uint32_t kCaePolicyCount = 5;

static_assert(sizeof(CaePolicyId) == sizeof(uint8_t));
static_assert(static_cast<uint8_t>(CaePolicyId::Neutral) == 0);
static_assert(static_cast<uint8_t>(CaePolicyId::Protect) == 1);
static_assert(static_cast<uint8_t>(CaePolicyId::ProtectStrong) == 2);
static_assert(static_cast<uint8_t>(CaePolicyId::Deprioritize) == 3);
static_assert(static_cast<uint8_t>(CaePolicyId::DeprioritizeStrong) == 4);

/**
*  @brief Upper bound on any frame, policy-map, cell, grid or block dimension. The spatial
*  mapping forms (2 * pixel + 1) * mapExtent, so every axis is checked against this cap before
*  any uint32_t to int32_t narrowing into the kernel parameters.
*/
inline constexpr uint32_t kMaxDimension = 65535;

/**
*  @brief Non-owning view of the pitched GPU U8 policy map the application selected for one
*  conversion. The owner guarantees that devicePtr names device memory reachable from the
*  converter's context and that capacityBytes is truthful; neither is queried per frame. Keep
*  the allocation alive and unmodified until that conversion's destination completion event has
*  completed successfully, and enqueue a wait on that event before the next write to the same
*  source slot. The converter retains nothing of this view.
*/
struct PolicyMapView
{
    /** First byte of cell (0, 0). Nonzero. */
    CUdeviceptr devicePtr{};

    /** Byte stride between vertically adjacent cells. Must be >= mapSizeCells.width. */
    uint64_t rowPitchBytes{};

    /**
    *  @brief Bytes readable from devicePtr. Must cover the span this view's own geometry
    *  requires, that is (mapSizeCells.height - 1) * rowPitchBytes + mapSizeCells.width.
    */
    uint64_t capacityBytes{};

    /** Valid policy rectangle, in cells. Both extents must be in [1, kMaxDimension]. */
    Extent2D mapSizeCells{};

    /**
    *  @brief How those cells lie over the destination view's frame. An empty optional is
    *  invalid: an omitted registration must fail loudly rather than silently become a
    *  plausible but spatially wrong scale-to-frame map.
    */
    std::optional<SpatialMapping> spatialMapping{};
};

class PolicyMapToDeltaQpConverter;

/**
*  @brief Non-owning view of an encoder-compatible signed-int8 delta-QP map. The bundled
*  adapter authors it, through EncoderFrameLease::GetDeltaQpWriteTarget(). The five layout
*  fields below are immutable for one registered allocation, and the owner zero-fills the whole
*  capacity once before first use, so the padding outside the active block rectangle stays
*  neutral for the life of the allocation.
*/
struct DeltaQpMapView
{
    /** First byte of block (0, 0). Nonzero. */
    CUdeviceptr devicePtr{};

    /** Byte stride between vertically adjacent block rows. Must be >= mapSizeBlocks.width. */
    uint64_t rowPitchBytes{};

    /**
    *  @brief True allocation capacity, not merely the active span. All of it is protected from
    *  overlapping source reads and all of it must hold defined bytes: this contract places no
    *  bound on how much of a registered surface a given NVENC implementation reads.
    */
    uint64_t capacityBytes{};

    /** Encoded frame size in luma samples. Both extents must be in [1, kMaxDimension]. */
    Extent2D frameSizePixels{};

    /**
    *  @brief Active delta-QP grid, in blocks. Both extents must be in [1, kMaxDimension] and
    *  must equal ceil(frameSizePixels / blockSizePixels) on both axes.
    */
    Extent2D mapSizeBlocks{};

    /**
    *  @brief Codec block footprint in luma samples: one output byte per width x height region.
    *  It must equal the footprint of the profile the converter was created with. A destination
    *  addressed in another codec's grid is the one descriptor error that would otherwise
    *  produce a plausible-looking map pointing at the wrong content.
    */
    Extent2D blockSizePixels{};
};

/**
*  @brief The destination owner's pairing of one delta-QP destination with the event the
*  converter records after writing it. That event is both the destination-readiness fence and
*  the source-consumption fence; it does not release the destination, which the encoder holds
*  until NVENC retires the encode slot. The bundled adapter hands the pair out together; the
*  type is an aggregate, so whoever constructs one is responsible for pairing it truthfully.
*/
struct DeltaQpWriteTarget
{
    DeltaQpMapView view{};
    CUevent completionEvent{};  // destination owner owns it; converter records it
};

/**
*  @brief Opaque, immutable, encoder-authored session token carrying the resolved
*  policy-to-delta values and the codec's delta-QP block footprint. Obtain one from
*  NvEncoderCudaDeltaQpMap::GetPolicyToDeltaQpProfile(), or from
*  ResolvePolicyToDeltaQpProfileForNvencGuid() in NvEncoderCudaDeltaQpMap.h, and pass it
*  to Create(). A default-constructed profile is the invalid sentinel and Create() rejects it.
*  Copyable, so the encoder adapter need not outlive the converter.
*/
class PolicyToDeltaQpProfile
{
public:
    PolicyToDeltaQpProfile() noexcept = default;  // invalid sentinel

    /**
    *  @brief True only for a profile a successful resolver or factory call populated.
    */
    [[nodiscard]] bool IsValid() const noexcept;

    /**
    *  @brief The codec's delta-QP block footprint in luma samples, or {0, 0} for the invalid
    *  sentinel. It is the one layout number the destination owner cannot invent, because
    *  DeltaQpMapView::mapSizeBlocks must equal ceil(frameSizePixels / this value) on both axes.
    *  The resolved deltas beside it are session policy and are deliberately not published; an
    *  application that could restate them would be choosing codec-specific quantizer offsets.
    */
    [[nodiscard]] Extent2D DeltaQpBlockSizePixels() const noexcept;

private:
    /* The converter reads the resolved deltas and the footprint directly; that is the only
     * reason it is a friend. The encoder adapter is not a friend: it obtains a token from the
     * resolver instead. */
    friend class PolicyMapToDeltaQpConverter;
    friend class detail::PolicyToDeltaQpProfileFactory;

    uint8_t profileKind_{};                         // CaeProfileKind; zero is the invalid kind
    int8_t deltaQpByPolicy_[kCaePolicyCount]{};     // resolved delta per CaePolicyId ordinal
    Extent2D blockSizePixels_{};                    // codec delta-QP block footprint
    int8_t minDeltaQp_{};                           // minDeltaQp_ <= 0 <= maxDeltaQp_, and
    int8_t maxDeltaQp_{};                           // every resolved delta lies inside

    PolicyToDeltaQpProfile(
        uint8_t profileKind,
        const int8_t (&deltaQpByPolicy)[kCaePolicyCount],
        Extent2D blockSizePixels,
        int8_t minDeltaQp,
        int8_t maxDeltaQp) noexcept;
};

/**
*  @brief Converts a policy-ID map into a delta-QP map on a borrowed conversion stream. It is
*  created once from that stream and an encoder-authored profile, and owns no source,
*  destination, event, stream, context, ring, registration or mapping, so successive calls may
*  name different allocations in any pairing without rebuilding anything. The caller serializes
*  the calls made through one converter and keeps the stream's context current on the calling
*  thread; there is no hidden mutex and no per-frame current-context query.
*/
class PolicyMapToDeltaQpConverter
{
public:
    PolicyMapToDeltaQpConverter() noexcept;
    PolicyMapToDeltaQpConverter(const PolicyMapToDeltaQpConverter&) = delete;
    PolicyMapToDeltaQpConverter& operator=(const PolicyMapToDeltaQpConverter&) = delete;
    PolicyMapToDeltaQpConverter(PolicyMapToDeltaQpConverter&&) noexcept;
    PolicyMapToDeltaQpConverter& operator=(PolicyMapToDeltaQpConverter&&) = delete;

    /**
    *  @brief Releases host-only state and performs no CUDA call, so it needs no current
    *  context and drains nothing. Quiesce every stream carrying conversion or encode work
    *  before destroying the borrowed buffers, events, stream or context; destroying an event
    *  is ordered against the queued work that names it, never against this object.
    */
    ~PolicyMapToDeltaQpConverter() noexcept;

    /**
    *  @brief Records the conversion stream and its context, adopts the profile and resolves
    *  the conversion kernel. This is a setup call and enqueues no GPU work. The stream is
    *  borrowed and must be an explicit non-blocking stream whose context is current on the
    *  calling thread; this is the only call that verifies currency, returning ContextMismatch.
    *  Returns InvalidArgument for a null or non-empty out, a null, legacy, per-thread or
    *  blocking stream, or an invalid profile, and OutOfMemory or CudaError from setup.
    */
    [[nodiscard]] static Status Create(
        CUstream conversionStream,
        const PolicyToDeltaQpProfile& policyToDeltaQpProfile,
        PolicyMapToDeltaQpConverter* out) noexcept;

    /**
    *  @brief False for a default-constructed or moved-from converter.
    */
    [[nodiscard]] bool IsValid() const noexcept;

    /**
    *  @brief Converts one policy map into the destination of one encoder lease. The documented
    *  per-frame sequence is: the source owner records its source-ready event, the application
    *  acquires one encoder lease, takes that lease's DeltaQpWriteTarget, calls this function,
    *  marks the conversion submitted, then moves that same lease into the encode call. This
    *  overload delegates to the four-argument one, which is the only validation and submission
    *  path, and it returns exactly what the delegated call returned.
    */
    [[nodiscard]] Status ConvertAsync(
        const PolicyMapView& policyMapView,
        const DeltaQpWriteTarget& deltaQpWriteTarget,
        CUevent policyMapReadyEvent) const noexcept;

    /**
    *  @brief Enqueues one conversion on the conversion stream: a wait on policyMapReadyEvent,
    *  one kernel, then a record of deltaQpMapReadyEvent, and nothing else. Success means
    *  submitted, not complete. Validation, geometry, capacity and overlap failures enqueue no
    *  work, and so does a failure of the source wait. Both events are required, distinct, owned
    *  outside the converter and associated with its context, and the producer must already have
    *  recorded policyMapReadyEvent.
    */
    [[nodiscard]] Status ConvertAsync(
        const PolicyMapView& policyMapView,
        const DeltaQpMapView& deltaQpMapView,
        CUevent policyMapReadyEvent,
        CUevent deltaQpMapReadyEvent) const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/* The normative reduction. For output block (bx, by), take every encoded luma pixel centre with
 * px in [bx * blockW, min((bx + 1) * blockW, frameW)) and py likewise on the vertical axis, map
 * each to a policy cell, then average the resolved deltas with equal weight, rounding half away
 * from zero. All of it is integer arithmetic, so host and device agree bit-exactly.
 *
 *      ScaleToFrameMapping   cx = ((2 * px + 1) * mapW) / (2 * frameW)
 *                            cy = ((2 * py + 1) * mapH) / (2 * frameH)
 *      FixedCellMapping      cx = px / cellW,  cy = py / cellH
 *
 *      numer = sum over the footprint of deltaQpByPolicy[policyMap[cy][cx]]
 *      denom = number of pixels in the footprint
 *      out   = roundHalfAwayFromZero(numer / denom)
 *
 * A source byte at or beyond kCaePolicyCount contributes a neutral 0. Every resolved delta lies
 * within the profile's legal range, so the mean does too and no clamp is performed. The mapping is
 * monotone in px and py, so an implementation may instead iterate covered cells weighted by covered
 * pixel count, as the device kernel does, and must produce the identical value.
 */

}   // namespace cae
}   // namespace nvcodec
