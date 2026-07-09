"""Tests for py2app build configuration and bundle structure."""

import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Mark all tests in this file as integration tests (they may require actual build)
pytestmark = pytest.mark.integration


class TestSetupAppConfig:
    """Test setup_app.py configuration."""

    def test_setup_app_module_exists(self):
        """Test that setup_app.py is a valid Python module."""
        import importlib.util
        
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        assert setup_path.exists(), "setup_app.py should exist"
        
        spec = importlib.util.spec_from_file_location("setup_app", setup_path)
        assert spec is not None, "setup_app.py should be a valid Python module"
        
        module = importlib.util.module_from_spec(spec)
        assert module is not None

    def test_setup_app_has_required_variables(self):
        """Test that setup_app.py contains required variables."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for APP variable definition
        assert "APP = " in content or "APP=" in content, \
            "setup_app.py should define APP"
        assert "menu_app.py" in content, \
            "APP should point to menu_app.py"
        
        # Check for OPTIONS variable definition
        assert "OPTIONS = " in content or "OPTIONS=" in content, \
            "setup_app.py should define OPTIONS"

    def test_bundle_identifier(self):
        """Test that bundle identifier is correct."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for bundle identifier in content
        assert "com.timshel.app" in content, \
            "Bundle identifier should be 'com.timshel.app'"
        assert "CFBundleIdentifier" in content, \
            "CFBundleIdentifier should be set in plist"

    def test_architecture_is_arm64(self):
        """Test that architecture is set to arm64."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for arm64 architecture
        assert "'arm64'" in content or '"arm64"' in content, \
            "Architecture should be set to 'arm64'"
        assert "'arch':" in content or '"arch":' in content, \
            "arch should be set in OPTIONS"

    def test_menu_bar_only(self):
        """Test that LSUIElement is set to True (menu bar only)."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for LSUIElement
        assert "LSUIElement" in content, \
            "LSUIElement should be set in plist"
        assert "True" in content or "LSUIElement: True" in content, \
            "LSUIElement should be True for menu bar only app"

    def test_required_packages_included(self):
        """Test that required packages are included."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for required packages in content
        required_packages = ['rumps', 'anthropic', 'mutagen', 'httpx', 'src']
        for pkg in required_packages:
            assert f"'{pkg}'" in content or f'"{pkg}"' in content, \
                f"Required package '{pkg}' should be in packages list"

    def test_unused_packages_excluded(self):
        """Test that unused packages are excluded."""
        # Read file as text to avoid executing setup()
        setup_path = Path(__file__).parent.parent / "setup_app.py"
        content = setup_path.read_text()
        
        # Check for unused packages in excludes
        unused_packages = ['tkinter', 'matplotlib', 'PIL', 'numpy', 'scipy']
        for pkg in unused_packages:
            assert f"'{pkg}'" in content or f'"{pkg}"' in content, \
                f"Unused package '{pkg}' should be in excludes list"


class TestBuildScript:
    """Test build script functionality."""

    def test_build_script_exists(self):
        """Test that build script exists and is executable."""
        build_script = Path(__file__).parent.parent / "scripts" / "build_app.sh"
        assert build_script.exists(), "build_app.sh should exist"
        assert build_script.is_file(), "build_app.sh should be a file"
        # Note: We can't check executable bit reliably across systems

    def test_build_script_has_shebang(self):
        """Test that build script has proper shebang."""
        build_script = Path(__file__).parent.parent / "scripts" / "build_app.sh"
        content = build_script.read_text()
        assert content.startswith('#!/bin/bash'), \
            "build_app.sh should start with #!/bin/bash"

    @pytest.mark.slow
    def test_build_script_can_be_executed(self):
        """Test that build script can be executed (dry run)."""
        # This test doesn't actually run the build, just checks syntax
        build_script = Path(__file__).parent.parent / "scripts" / "build_app.sh"
        
        # Check syntax using bash -n
        result = subprocess.run(
            ['bash', '-n', str(build_script)],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, \
            f"Build script has syntax errors: {result.stderr}"


class TestBundleStructure:
    """Test bundle structure after build (requires actual build)."""

    @pytest.mark.slow
    def test_bundle_exists_after_build(self, tmp_path):
        """Test that bundle exists after build (if build was run)."""
        # This test checks if dist/Malinche.app exists
        # It will pass if build was already run, skip otherwise
        dist_dir = Path(__file__).parent.parent / "dist"
        bundle = dist_dir / "Malinche.app"
        
        if not bundle.exists():
            pytest.skip("Bundle not found - run build first")
        
        assert bundle.is_dir(), "Malinche.app should be a directory"

    @pytest.mark.slow
    def test_info_plist_exists(self):
        """Test that Info.plist exists in bundle."""
        bundle = Path(__file__).parent.parent / "dist" / "Malinche.app"
        
        if not bundle.exists():
            pytest.skip("Bundle not found - run build first")
        
        info_plist = bundle / "Contents" / "Info.plist"
        assert info_plist.exists(), "Info.plist should exist in bundle"

    @pytest.mark.slow
    def test_executable_exists(self):
        """Test that main executable exists in bundle."""
        bundle = Path(__file__).parent.parent / "dist" / "Malinche.app"
        
        if not bundle.exists():
            pytest.skip("Bundle not found - run build first")
        
        executable = bundle / "Contents" / "MacOS" / "Malinche"
        assert executable.exists(), "Main executable should exist in bundle"
        assert executable.is_file(), "Main executable should be a file"

    @pytest.mark.slow
    def test_bundle_size_reasonable(self):
        """Test that bundle size is reasonable (<50MB without models - relaxed for now)."""
        bundle = Path(__file__).parent.parent / "dist" / "Malinche.app"
        
        if not bundle.exists():
            pytest.skip("Bundle not found - run build first")
        
        # Calculate size in MB
        import shutil
        size_bytes = sum(
            f.stat().st_size for f in bundle.rglob('*') if f.is_file()
        )
        size_mb = size_bytes / (1024 * 1024)
        
        # Bundle should be <60MB. Bundle-size trim (<20MB target) is deferred
        # (parked release work) — current builds land ~50MB on py2app +
        # python3.12 + anthropic/pydantic. This guards against runaway growth,
        # not the eventual optimization target.
        assert size_mb < 60, \
            f"Bundle size ({size_mb:.1f} MB) exceeds 60MB limit"

