import platform
from pathlib import Path

def main():
    """Setup REAPER integration"""
    if platform.system() == "Darwin":
        reaper_path = Path.home() / "Library/Application Support/REAPER"
    elif platform.system() == "Windows":
        reaper_path = Path.home() / "AppData/Roaming/REAPER"
    else:
        reaper_path = Path.home() / ".config/REAPER"
    
    if not reaper_path.exists():
        print(f"REAPER not found at {reaper_path}")
        return
    
    print(f"Setting up REAPER integration at: {reaper_path}")

    project_root = Path.cwd()
    scripts_src = project_root / "src" / "Scripts" / "MIDI-GPT"

    print(f"Linking:\n    - {scripts_src}")

    scripts_dst = reaper_path / "Scripts" / "MIDI-GPT"

    if scripts_src.exists():
        if scripts_dst.exists():
            scripts_dst.unlink()
        scripts_dst.symlink_to(scripts_src)
        print(f"Scripts symlinked: {scripts_dst}")

    user_plugins = reaper_path / "UserPlugins"
    if not any(user_plugins.glob("*imgui*")) and not any(user_plugins.glob("*ImGui*")):
        print("\nWARNING: ReaImGui extension not found -- the dashboard UI needs it.")
        print("  In REAPER: Extensions > ReaPack > Browse packages > search 'ReaImGui'")
        print("  (Don't have ReaPack? Get it first: https://reapack.com/)")

if __name__ == "__main__":
    main()