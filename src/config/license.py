import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple


from src.config.features import FeatureFlags, FeatureTier

# NOTE: ``src.logger`` imports ``src.config`` which in turn imports this module.
# Importing the logger at module top-level therefore creates a circular import
# (ImportError: cannot import name 'logger' from partially initialized module
# 'src.logger'). Using lazy, function-level imports keeps the public behaviour
# identical while breaking the cycle.


class LicenseManager:
    """Manages license verification and feature access."""

    LICENSE_API = "https://api.malinche.app/v1/license"
    CACHE_VALIDITY_DAYS = 7

    def __init__(self):
        self._cached_tier: Optional[FeatureTier] = None
        self._license_key: Optional[str] = None
        self._load_stored_license()

    def get_current_tier(self) -> FeatureTier:
        """Get current license tier (cached)."""
        if self._cached_tier is None:
            self._cached_tier = self._verify_license()
        return self._cached_tier

    def get_features(self) -> FeatureFlags:
        """Get enabled features based on license."""
        return FeatureFlags.for_tier(self.get_current_tier())

    def activate_license(self, key: str) -> Tuple[bool, str]:
        """Activate a license key. Returns (success, message)."""
        from src.logger import logger

        # Placeholder for v2.0.0 FREE - currently no backend to activate against
        logger.info(f"Attempting to activate license key: {key[:4]}...")
        
        # In real implementation this would call the backend
        # try:
        #     response = httpx.post(f"{self.LICENSE_API}/activate", json={"key": key}, timeout=10.0)
        #     ...
        # except Exception as e:
        #     return False, f"Connection error: {e}"

        return False, "Aktywacja licencji nie jest jeszcze dostępna w wersji FREE."

    def deactivate_license(self) -> None:
        """Deactivate current license."""
        self._license_key = None
        self._cached_tier = FeatureTier.FREE
        license_file = self._license_path()
        if license_file.exists():
            license_file.unlink()
        cache_file = self._cache_path()
        if cache_file.exists():
            cache_file.unlink()

        from src.logger import logger

        logger.info("License deactivated")

    def get_usage_limits(self) -> Dict:
        """Get usage limits for the current tier."""
        # TODO: Implement actual limits from backend
        tier = self.get_current_tier()
        if tier == FeatureTier.PRO_ORG:
            return {"minutes_monthly": 1000, "unlimited": True}
        elif tier == FeatureTier.PRO:
            return {"minutes_monthly": 300, "unlimited": False}
        return {"minutes_monthly": 0, "unlimited": False}

    def _verify_license(self) -> FeatureTier:
        """Resolve the active tier: a valid local cache wins, else the default.

        Beta: there is no licensing backend yet, so every install is granted
        PRO — beta testers get the full feature set without a key. A still-valid
        cached tier is honoured if present. At GA this default flips back to
        FREE and real verification against ``LICENSE_API`` takes over.
        """
        cached = self._load_cache()
        if cached:
            try:
                expires = datetime.fromisoformat(cached["expires"])
                if expires > datetime.now():
                    return FeatureTier(cached["tier"])
            except (ValueError, KeyError):
                pass

        # Beta: unconditionally unlock PRO (no backend / license key required).
        return FeatureTier.PRO

    def _load_stored_license(self) -> None:
        """Load license key from secure storage."""
        license_file = self._license_path()
        if license_file.exists():
            try:
                data = json.loads(license_file.read_text(encoding="utf-8"))
                self._license_key = data.get("key")
            except (json.JSONDecodeError, AttributeError):
                pass

    def _save_license(self) -> None:
        """Save license key to secure storage."""
        license_file = self._license_path()
        license_file.parent.mkdir(parents=True, exist_ok=True)
        license_file.write_text(json.dumps({"key": self._license_key}), encoding="utf-8")

    def _license_path(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Timshel" / "license.json"

    def _cache_path(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Timshel" / "license_cache.json"

    def _load_cache(self) -> Optional[dict]:
        cache_file = self._cache_path()
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return None

    def _save_cache(self, tier: FeatureTier) -> None:
        cache_file = self._cache_path()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        expires = datetime.now() + timedelta(days=self.CACHE_VALIDITY_DAYS)
        cache_file.write_text(
            json.dumps({"tier": tier.value, "expires": expires.isoformat()}),
            encoding="utf-8"
        )


# Global instance
license_manager = LicenseManager()
