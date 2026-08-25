from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = "claude-haiku-4-5"


def main() -> None:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system="You are a concise assistant. Answer in one short sentence.",
        messages=[
            {"role": "user", "content": "In one sentence: what is the Anthropic Messages API?"}
        ],
    )

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "api.json").write_text(
        response.model_dump_json(indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
