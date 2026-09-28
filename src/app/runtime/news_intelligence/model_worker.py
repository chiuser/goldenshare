from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M1 frozen-model JSONL worker.")
    subparsers = parser.add_subparsers(dest="stage", required=True)
    embedding = subparsers.add_parser("embedding")
    embedding.add_argument("--model-path", required=True, type=Path)
    embedding.add_argument(
        "--max-tokens", type=int, default=512, choices=range(1, 513), metavar="1..512"
    )
    nli = subparsers.add_parser("nli")
    nli.add_argument("--model-path", required=True, type=Path)
    nli.add_argument("--onnx-path", required=True, type=Path)
    nli.add_argument(
        "--max-tokens", type=int, default=512, choices=range(1, 513), metavar="1..512"
    )
    nli.add_argument(
        "--batch-size", type=int, default=16, choices=range(1, 17), metavar="1..16"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.stage == "embedding":
        return _run_embedding(args.model_path, args.max_tokens)
    if args.stage == "nli":
        return _run_nli(
            args.model_path, args.onnx_path, args.max_tokens, args.batch_size
        )
    raise AssertionError(f"unsupported stage: {args.stage}")


def _run_embedding(model_path: Path, max_tokens: int) -> int:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(model_path), local_files_only=True, device="cpu")
    model.max_seq_length = max_tokens
    for request in _requests():
        text = _required_text(request, "text")
        vector = model.encode(
            [text],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )[0]
        _respond(
            {
                "request_id": request.get("request_id"),
                "embedding": [float(value) for value in vector],
            }
        )
    return 0


def _run_nli(
    model_path: Path, onnx_path: Path, max_tokens: int, batch_size: int
) -> int:
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_names = {item.name for item in session.get_inputs()}
    entailment_index = _entailment_index(model_path)
    for request in _requests():
        premise = _required_text(request, "premise")
        hypotheses = request.get("hypotheses")
        if (
            not isinstance(hypotheses, list)
            or not hypotheses
            or not all(isinstance(value, str) for value in hypotheses)
        ):
            raise ValueError("hypotheses must be a non-empty string list")
        if len(hypotheses) > batch_size:
            raise ValueError(f"hypotheses exceed frozen batch size {batch_size}")
        encoded = tokenizer(
            [premise] * len(hypotheses),
            hypotheses,
            padding=True,
            truncation=True,
            max_length=max_tokens,
            return_tensors="np",
        )
        inputs = {
            name: np.asarray(value, dtype=np.int64)
            for name, value in encoded.items()
            if name in input_names
        }
        logits = session.run(None, inputs)[0]
        probabilities = _softmax(logits)
        _respond(
            {
                "request_id": request.get("request_id"),
                "entailment_scores": [
                    float(value) for value in probabilities[:, entailment_index]
                ],
            }
        )
    return 0


def _requests():
    for line_number, line in enumerate(sys.stdin, start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"request line {line_number} must be an object")
        yield value


def _required_text(request: dict[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _respond(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def _softmax(values):
    import numpy as np

    shifted = values - np.max(values, axis=-1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / np.sum(exponentials, axis=-1, keepdims=True)


def _entailment_index(model_path: Path) -> int:
    config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    label_to_id = config.get("label2id")
    if isinstance(label_to_id, dict):
        for label, index in label_to_id.items():
            if str(label).casefold() == "entailment" and isinstance(index, int):
                return index
    id_to_label = config.get("id2label")
    if isinstance(id_to_label, dict):
        for index, label in id_to_label.items():
            if str(label).casefold() == "entailment":
                return int(index)
    raise ValueError("frozen NLI config does not define an entailment label")


if __name__ == "__main__":
    raise SystemExit(main())
