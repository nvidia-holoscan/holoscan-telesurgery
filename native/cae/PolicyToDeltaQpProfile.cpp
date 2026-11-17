/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
*  This file holds the only copy of the normative H.264, HEVC and AV1 policy-to-delta-QP tables,
*  the only factory that accepts raw signed deltas, and the pure GUID resolver that turns an
*  authoritative NVENC codec GUID into an opaque PolicyToDeltaQpProfile. Everything here is host
*  arithmetic, so the encoder adapter, the converter and the hardware-free tests all link it
*  without a second copy of the numbers.
*
*  A tuning change updates the tables here and the independently transcribed expected literals in
*  the tests together, in one revision.
*/

#include "PolicyMapToDeltaQp.h"

#include <nvEncodeAPI.h>

#include <cstdint>

namespace nvcodec {
namespace cae {

/* Which codec's table a profile carries. Zero is the reserved invalid kind, so a value-initialized
 * profile cannot mean H.264; the profile stores it as a plain uint8_t and this is the only
 * interpretation of that byte. */
enum class CaeProfileKind : uint8_t
{
    Invalid = 0,
    H264 = 1,
    Hevc = 2,
    Av1 = 3
};

/* Uses no session, device or NVENC entry point. out is set to CaeProfileKind::Invalid on every
 * failure. */
[[nodiscard]] Status ResolveCaeProfileKindForNvencGuid(GUID encodeGuid,
                                                       CaeProfileKind* out) noexcept;

namespace detail {

/* The only way private profile state is written, or read outside the converter. All members are
 * static; the class exists to be a friend of PolicyToDeltaQpProfile, not to be instantiated. */
class PolicyToDeltaQpProfileFactory
{
public:
    PolicyToDeltaQpProfileFactory() = delete;

    [[nodiscard]] static Status CreateFromRawValues(
        CaeProfileKind profileKind,
        const int8_t (&deltaQpByPolicy)[kCaePolicyCount],
        Extent2D blockSizePixels,
        int8_t minDeltaQp,
        int8_t maxDeltaQp,
        PolicyToDeltaQpProfile* out) noexcept;

    /* The converter deliberately does not call this: its creation-time revalidation is written
     * independently, so a defect in one implementation cannot pass both gates. */
    [[nodiscard]] static Status ValidateInvariants(const PolicyToDeltaQpProfile& profile) noexcept;

    [[nodiscard]] static CaeProfileKind ProfileKind(const PolicyToDeltaQpProfile& profile) noexcept;
    [[nodiscard]] static Extent2D BlockSizePixels(const PolicyToDeltaQpProfile& profile) noexcept;
    [[nodiscard]] static int8_t DeltaQpForPolicy(const PolicyToDeltaQpProfile& profile,
                                                 CaePolicyId policy) noexcept;
    [[nodiscard]] static int8_t MinDeltaQp(const PolicyToDeltaQpProfile& profile) noexcept;
    [[nodiscard]] static int8_t MaxDeltaQp(const PolicyToDeltaQpProfile& profile) noexcept;
};

}   // namespace detail

namespace {

// One codec's approved table. The three codecs are declared separately even where their deltas
// agree, so that re-tuning one is a single-row edit that cannot move the other two.
struct NormativeProfile
{
    CaeProfileKind kind;
    int8_t deltaQpByPolicy[kCaePolicyCount];
    Extent2D blockSizePixels;

    /* A validation bound on the table below, never a clamp applied to a computed block value. */
    int8_t minDeltaQp;
    int8_t maxDeltaQp;
};

/* The positional initializers below follow the enum's numbering exactly. */
static_assert(kCaePolicyCount == 5);
static_assert(static_cast<uint8_t>(CaePolicyId::Neutral) == 0);
static_assert(static_cast<uint8_t>(CaePolicyId::Protect) == 1);
static_assert(static_cast<uint8_t>(CaePolicyId::ProtectStrong) == 2);
static_assert(static_cast<uint8_t>(CaePolicyId::Deprioritize) == 3);
static_assert(static_cast<uint8_t>(CaePolicyId::DeprioritizeStrong) == 4);

/*                                                Neutral, Protect, ProtectStrong,
 *                                                Deprioritize, DeprioritizeStrong                */
constexpr NormativeProfile kProfileH264{CaeProfileKind::H264, {0, -4, -8, 4, 8},
                                        Extent2D{16, 16}, -51, 51};

constexpr NormativeProfile kProfileHevc{CaeProfileKind::Hevc, {0, -4, -8, 4, 8},
                                        Extent2D{32, 32}, -51, 51};

constexpr NormativeProfile kProfileAv1{CaeProfileKind::Av1, {0, -4, -8, 4, 8},
                                       Extent2D{64, 64}, -51, 51};

constexpr size_t PolicyIndex(CaePolicyId policy)
{
    return static_cast<size_t>(static_cast<uint8_t>(policy));
}

/* The invariants the factory enforces at run time, restated so a typo in a table above is a build
 * failure rather than a test failure. */
constexpr bool IsWellFormed(const NormativeProfile& profile)
{
    return profile.kind != CaeProfileKind::Invalid &&
           profile.blockSizePixels.width >= 1 && profile.blockSizePixels.width <= kMaxDimension &&
           profile.blockSizePixels.height >= 1 && profile.blockSizePixels.height <= kMaxDimension &&
           profile.minDeltaQp <= 0 && profile.maxDeltaQp >= 0 &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::Neutral)] == 0 &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::ProtectStrong)] <
               profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::Protect)] &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::Protect)] < 0 &&
           0 < profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::Deprioritize)] &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::Deprioritize)] <
               profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::DeprioritizeStrong)] &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::ProtectStrong)] >= profile.minDeltaQp &&
           profile.deltaQpByPolicy[PolicyIndex(CaePolicyId::DeprioritizeStrong)] <=
               profile.maxDeltaQp;
}

static_assert(IsWellFormed(kProfileH264));
static_assert(IsWellFormed(kProfileHevc));
static_assert(IsWellFormed(kProfileAv1));

Status MakeOk()
{
    return Status{};
}

Status MakeError(Error error, const char* message)
{
    Status status;
    status.error = error;
    status.cudaResult = CUDA_SUCCESS;
    status.message = message;
    return status;
}

/* Field-wise, because memcmp() would also read padding that NVENC's static GUID definitions do not
 * initialize on every platform. */
bool GuidEquals(const GUID& a, const GUID& b)
{
    if (a.Data1 != b.Data1 || a.Data2 != b.Data2 || a.Data3 != b.Data3)
    {
        return false;
    }
    for (size_t i = 0; i < sizeof(a.Data4) / sizeof(a.Data4[0]); ++i)
    {
        if (a.Data4[i] != b.Data4[i])
        {
            return false;
        }
    }
    return true;
}

// Null for a kind with no approved table.
const NormativeProfile* FindNormativeProfile(CaeProfileKind kind)
{
    switch (kind)
    {
    case CaeProfileKind::H264: return &kProfileH264;
    case CaeProfileKind::Hevc: return &kProfileHevc;
    case CaeProfileKind::Av1:  return &kProfileAv1;
    case CaeProfileKind::Invalid: break;
    }
    return nullptr;
}

}   // namespace

PolicyToDeltaQpProfile::PolicyToDeltaQpProfile(
    uint8_t profileKind,
    const int8_t (&deltaQpByPolicy)[kCaePolicyCount],
    Extent2D blockSizePixels,
    int8_t minDeltaQp,
    int8_t maxDeltaQp) noexcept
    : profileKind_(profileKind)
    , blockSizePixels_(blockSizePixels)
    , minDeltaQp_(minDeltaQp)
    , maxDeltaQp_(maxDeltaQp)
{
    for (size_t i = 0; i < kCaePolicyCount; ++i)
    {
        deltaQpByPolicy_[i] = deltaQpByPolicy[i];
    }
}

bool PolicyToDeltaQpProfile::IsValid() const noexcept
{
    /* Kind zero is reserved, so a default-constructed token is invalid without a separate flag that
     * could disagree with it. */
    return profileKind_ != static_cast<uint8_t>(CaeProfileKind::Invalid);
}

Extent2D PolicyToDeltaQpProfile::DeltaQpBlockSizePixels() const noexcept
{
    return detail::PolicyToDeltaQpProfileFactory::BlockSizePixels(*this);
}

namespace detail {

Status PolicyToDeltaQpProfileFactory::CreateFromRawValues(
    CaeProfileKind profileKind,
    const int8_t (&deltaQpByPolicy)[kCaePolicyCount],
    Extent2D blockSizePixels,
    int8_t minDeltaQp,
    int8_t maxDeltaQp,
    PolicyToDeltaQpProfile* out) noexcept
{
    if (out == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfileFactory::CreateFromRawValues() requires a non-null "
                         "out");
    }
    if (out->IsValid())
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfileFactory::CreateFromRawValues() requires an invalid "
                         "out; it never overwrites a resolved profile");
    }

    if (profileKind == CaeProfileKind::Invalid || FindNormativeProfile(profileKind) == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires a real CaeProfileKind; kind zero is the "
                         "reserved invalid sentinel");
    }

    if (blockSizePixels.width == 0 || blockSizePixels.height == 0 ||
        blockSizePixels.width > kMaxDimension || blockSizePixels.height > kMaxDimension)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile block extents must be in [1, kMaxDimension]");
    }

    /* The range must straddle zero: a block nobody has an opinion about resolves to a neutral 0. */
    if (minDeltaQp > 0 || maxDeltaQp < 0)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires minDeltaQp <= 0 <= maxDeltaQp");
    }

    const int8_t neutral = deltaQpByPolicy[PolicyIndex(CaePolicyId::Neutral)];
    const int8_t protect = deltaQpByPolicy[PolicyIndex(CaePolicyId::Protect)];
    const int8_t protectStrong = deltaQpByPolicy[PolicyIndex(CaePolicyId::ProtectStrong)];
    const int8_t deprioritize = deltaQpByPolicy[PolicyIndex(CaePolicyId::Deprioritize)];
    const int8_t deprioritizeStrong = deltaQpByPolicy[PolicyIndex(CaePolicyId::DeprioritizeStrong)];

    if (neutral != 0)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile requires CaePolicyId::Neutral to resolve to "
                         "exactly 0");
    }
    if (!(protectStrong < protect && protect < 0 && 0 < deprioritize &&
          deprioritize < deprioritizeStrong))
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

    *out = PolicyToDeltaQpProfile(static_cast<uint8_t>(profileKind), deltaQpByPolicy,
                                  blockSizePixels, minDeltaQp, maxDeltaQp);
    return MakeOk();
}

Status PolicyToDeltaQpProfileFactory::ValidateInvariants(
    const PolicyToDeltaQpProfile& profile) noexcept
{
    if (!profile.IsValid())
    {
        return MakeError(Error::InvalidArgument, "PolicyToDeltaQpProfile is invalid");
    }
    if (FindNormativeProfile(ProfileKind(profile)) == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "PolicyToDeltaQpProfile carries an unknown CaeProfileKind");
    }

    /* A temporary, because the construction gate below refuses to overwrite a valid profile. */
    PolicyToDeltaQpProfile probe;
    return CreateFromRawValues(ProfileKind(profile), profile.deltaQpByPolicy_,
                               profile.blockSizePixels_, profile.minDeltaQp_, profile.maxDeltaQp_,
                               &probe);
}

CaeProfileKind PolicyToDeltaQpProfileFactory::ProfileKind(
    const PolicyToDeltaQpProfile& profile) noexcept
{
    switch (profile.profileKind_)
    {
    case static_cast<uint8_t>(CaeProfileKind::H264): return CaeProfileKind::H264;
    case static_cast<uint8_t>(CaeProfileKind::Hevc): return CaeProfileKind::Hevc;
    case static_cast<uint8_t>(CaeProfileKind::Av1):  return CaeProfileKind::Av1;
    default: break;
    }
    return CaeProfileKind::Invalid;
}

Extent2D PolicyToDeltaQpProfileFactory::BlockSizePixels(
    const PolicyToDeltaQpProfile& profile) noexcept
{
    if (!profile.IsValid())
    {
        return Extent2D{};
    }
    return profile.blockSizePixels_;
}

int8_t PolicyToDeltaQpProfileFactory::DeltaQpForPolicy(const PolicyToDeltaQpProfile& profile,
                                                       CaePolicyId policy) noexcept
{
    /* A scoped enum can still be forged with static_cast<CaePolicyId>(255), so an out-of-range index
     * resolves to neutral rather than reading past the table. */
    const size_t index = PolicyIndex(policy);
    if (!profile.IsValid() || index >= kCaePolicyCount)
    {
        return 0;
    }
    return profile.deltaQpByPolicy_[index];
}

int8_t PolicyToDeltaQpProfileFactory::MinDeltaQp(const PolicyToDeltaQpProfile& profile) noexcept
{
    return profile.IsValid() ? profile.minDeltaQp_ : static_cast<int8_t>(0);
}

int8_t PolicyToDeltaQpProfileFactory::MaxDeltaQp(const PolicyToDeltaQpProfile& profile) noexcept
{
    return profile.IsValid() ? profile.maxDeltaQp_ : static_cast<int8_t>(0);
}

}   // namespace detail

Status ResolveCaeProfileKindForNvencGuid(GUID encodeGuid, CaeProfileKind* out) noexcept
{
    if (out == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "ResolveCaeProfileKindForNvencGuid() requires a non-null out");
    }

    *out = CaeProfileKind::Invalid;

    if (GuidEquals(encodeGuid, NV_ENC_CODEC_H264_GUID))
    {
        *out = CaeProfileKind::H264;
        return MakeOk();
    }
    if (GuidEquals(encodeGuid, NV_ENC_CODEC_HEVC_GUID))
    {
        *out = CaeProfileKind::Hevc;
        return MakeOk();
    }
    if (GuidEquals(encodeGuid, NV_ENC_CODEC_AV1_GUID))
    {
        *out = CaeProfileKind::Av1;
        return MakeOk();
    }

    /* No fallback codec: guessing here is how AV1 silently becomes H.264. */
    return MakeError(Error::Unsupported,
                     "NV_ENC_INITIALIZE_PARAMS::encodeGUID names no codec with an approved "
                     "policy-to-delta-QP profile");
}

Status ResolvePolicyToDeltaQpProfileForNvencGuid(GUID encodeGuid,
                                                 PolicyToDeltaQpProfile* out) noexcept
{
    if (out == nullptr)
    {
        return MakeError(Error::InvalidArgument,
                         "ResolvePolicyToDeltaQpProfileForNvencGuid() requires a non-null out");
    }
    if (out->IsValid())
    {
        return MakeError(Error::InvalidArgument,
                         "ResolvePolicyToDeltaQpProfileForNvencGuid() requires an invalid out; it "
                         "never overwrites a resolved profile");
    }

    CaeProfileKind kind = CaeProfileKind::Invalid;
    const Status kindStatus = ResolveCaeProfileKindForNvencGuid(encodeGuid, &kind);
    if (!kindStatus.IsOk())
    {
        return kindStatus;
    }

    const NormativeProfile* const table = FindNormativeProfile(kind);
    if (table == nullptr)
    {
        return MakeError(Error::Unsupported,
                         "no approved policy-to-delta-QP table for the resolved codec");
    }

    return detail::PolicyToDeltaQpProfileFactory::CreateFromRawValues(
        table->kind, table->deltaQpByPolicy, table->blockSizePixels, table->minDeltaQp,
        table->maxDeltaQp, out);
}

}   // namespace cae
}   // namespace nvcodec
