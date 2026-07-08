import webbrowser
import rumps
from src.config.license import license_manager
from src.config.features import FeatureTier


def show_pro_activation():
    """Show PRO activation dialog."""
    tier = license_manager.get_current_tier()

    if tier != FeatureTier.FREE:
        tier_name = "PRO Individual" if tier == FeatureTier.PRO else "PRO Organization"
        rumps.alert(
            title="✅ Timshel PRO",
            message=f"You already have an active {tier_name} subscription!",
        )
        return

    response = rumps.alert(
        title="🚀 Timshel PRO",
        message=(
            "Unlock the full Timshel feature set:\n\n"
            "⭐ AI summaries and titles\n"
            "⭐ Smart Obsidian tags\n"
            "⭐ Diarization (who spoke when)\n"
            "⭐ Shared knowledge (PRO Org)\n\n"
            "PRO Individual subscription from $9/month."
        ),
        ok="Buy PRO",
        cancel="I already have a key",
    )

    if response == 1:
        webbrowser.open("https://timshel.app/pro")
    elif response == 0:
        key_response = rumps.Window(
            title="PRO activation",
            message="Paste your license key:",
            ok="Activate",
            cancel="Cancel",
            dimensions=(300, 24),
        ).run()

        if key_response.clicked == 1 and key_response.text:
            success, message = license_manager.activate_license(key_response.text.strip())
            rumps.alert(
                title="✅ Success" if success else "❌ Error",
                message=message,
            )


def show_pro_status():
    """Check and show current license status."""
    tier = license_manager.get_current_tier()
    if tier == FeatureTier.FREE:
        show_pro_activation()
    else:
        limits = license_manager.get_usage_limits()
        tier_name = "PRO Individual" if tier == FeatureTier.PRO else "PRO Organization"

        message = f"Active subscription: {tier_name}\n"
        if not limits.get("unlimited"):
            message += f"Minutes remaining: {limits.get('minutes_monthly', 0)} / month"
        else:
            message += "Unlimited processing"

        rumps.alert(
            title="💎 Timshel PRO status",
            message=message,
        )
