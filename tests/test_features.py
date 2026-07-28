import pytest
from src.config.features import FeatureTier, FeatureFlags


class TestFeatureFlags:
    def test_free_tier_defaults(self):
        """FREE tier should only have basic features enabled."""
        flags = FeatureFlags.for_tier(FeatureTier.FREE)
        assert flags.recorder_detection is True
        assert flags.markdown_export is True
        assert flags.basic_tags is True
        assert flags.ai_summaries is False
        assert flags.ai_smart_tags is False
        assert flags.speaker_diarization is False
        assert flags.cloud_sync is False

    def test_pro_tier_enables_ai_features(self):
        """PRO tier should enable AI features and local diarization."""
        flags = FeatureFlags.for_tier(FeatureTier.PRO)
        assert flags.ai_summaries is True
        assert flags.ai_smart_tags is True
        assert flags.speaker_diarization is True
        assert flags.cloud_sync is False
        assert flags.knowledge_base is False

    def test_pro_org_tier_enables_all_features(self):
        """PRO_ORG tier should enable all features including knowledge base."""
        flags = FeatureFlags.for_tier(FeatureTier.PRO_ORG)
        assert flags.ai_summaries is True
        assert flags.cloud_sync is True
        assert flags.shared_speaker_db is True
        assert flags.knowledge_base is True

    def test_can_use_method(self):
        """can_use method should correctly check feature availability."""
        flags = FeatureFlags(ai_summaries=True, cloud_sync=False)
        assert flags.can_use("ai_summaries") is True
        assert flags.can_use("cloud_sync") is False
        assert flags.can_use("non_existent") is False
