import argparse
import json
from pathlib import Path

from . import publish, verify_recording, compile_recording, open_dataset


def main():
    parser = argparse.ArgumentParser(description="DSP single-episode recording integration")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("finish", "verify", "compile", "inspect"):
        sub = commands.add_parser(command)
        sub.add_argument("--source", type=Path, required=True)
        if command != "inspect":
            sub.add_argument("--ffmpeg", type=Path, required=True)
        if command == "compile":
            sub.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "finish":
        evidence = args.source.with_name(args.source.name + ".evidence")
        dataset = args.source.with_name(args.source.name + ".dataset")
        publish(args.source, evidence, args.ffmpeg)
        compile_recording(evidence, dataset, args.ffmpeg)
        result = open_dataset(dataset)
        print(json.dumps(dict(evidence=str(evidence), dataset=str(dataset), transitions=len(result),
                              source_kind=result.metadata["source_kind"])))
    elif args.command == "verify":
        manifest, _, _ = verify_recording(args.source, args.ffmpeg)
        print(json.dumps(manifest, indent=2))
    elif args.command == "compile":
        compile_recording(args.source, args.out, args.ffmpeg)
    else:
        dataset = open_dataset(args.source)
        print(json.dumps(dict(metadata=dataset.metadata, transitions=len(dataset), first_source=dataset[0]["source"]), indent=2))


if __name__ == "__main__":
    main()
