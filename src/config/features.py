from enum import Enum
from dataclasses import dataclass


class FeatureTier(Enum):
    """Available subscription tiers for Timshel."""

    FREE = "free"
    PRO = "pro"  # PRO Individual (Monthly Subscription)
    PRO_ORG = "pro_org"  # PRO Organization (Monthly Subscription)


@dataclass(frozen=True)
class FeatureFlags:
    """Feature flags enabled for a specific tier."""

    # FREE features (always enabled)
    recorder_detection: bool = True
    markdown_export: bool = True
    basic_tags: bool = True

    # PRO Individual features
    ai_summaries: bool = False
    ai_smart_tags: bool = False
    ai_naming: bool = False
    connection_synthesis: bool = False  # "Zestawianie": cross-note synthesis digest
    speaker_diarization: bool = False  # Local diarization

    # PRO Organization features
    cloud_sync: bool = False
    shared_speaker_db: bool = False
    domain_lexicon: bool = False
    knowledge_base: bool = False

    @classmethod
    def for_tier(cls, tier: FeatureTier) -> "FeatureFlags":
        """Get feature flags configuration for a specific tier."""
        if tier == FeatureTier.PRO_ORG:
            return cls(
                ai_summaries=True,
                ai_smart_tags=True,
                ai_naming=True,
                connection_synthesis=True,
                speaker_diarization=True,
                cloud_sync=True,
                shared_speaker_db=True,
                domain_lexicon=True,
                knowledge_base=True,
            )
        elif tier == FeatureTier.PRO:
            return cls(
                ai_summaries=True,
                ai_smart_tags=True,
                ai_naming=True,
                connection_synthesis=True,
                speaker_diarization=True,
            )
        # FREE defaults
        return cls()

    def can_use(self, feature: str) -> bool:
        """Check if a specific feature is enabled in these flags."""
        return getattr(self, feature, False)
