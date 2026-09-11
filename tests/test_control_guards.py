from pathlib import Path
import subprocess


def test_built_and_deployed_plugins_reject_policy_during_human_recording():
    root = Path(__file__).resolve().parents[1]
    game = Path(r"E:\Steam\steamapps\common\Dyson Sphere Program")
    project = root / "tests/ControlGuards/ControlGuards.csproj"
    subprocess.run(["dotnet", "build", str(project), "--no-restore", "--configuration", "Release"],
                   check=True, capture_output=True)
    source = root / "src/DSPDreamer.Recorder"
    subprocess.run(["dotnet", "build", str(source / "DSPDreamer.Recorder.csproj"),
                    "--no-restore", "--configuration", "Release"], check=True, capture_output=True)
    for dll in (source / "bin/Release/DSPDreamer.Recorder.dll",
                game / "BepInEx/plugins/DSPDreamer/DSPDreamer.Recorder.dll"):
        result = subprocess.check_output([
            str(root / "tests/ControlGuards/bin/Release/net472/ControlGuards.exe"), str(dll),
            str(game / "BepInEx/core"), str(game / "DSPGAME_Data/Managed")], text=True, timeout=30)
        assert "human-policy guards passed" in result
