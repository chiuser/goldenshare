from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

from src.biz.services.wealth.news_intelligence.policy import (
    EMBEDDING_MAX_TOKENS,
    NLI_BATCH_SIZE,
    NLI_MAX_TOKENS,
)

from .model_process import ModelProcessError, SerializedModelProcess


@dataclass(frozen=True, slots=True)
class FrozenModelPaths:
    runtime_root: Path
    python: Path
    embedding_model: Path
    nli_model: Path
    nli_onnx: Path
    llama_server: Path
    qwen_model: Path

    @classmethod
    def from_root(cls, root: Path) -> "FrozenModelPaths":
        root = root.expanduser().resolve()
        nli_model = (
            root
            / "models/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli/8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
        )
        return cls(
            runtime_root=root,
            python=root / "runtime/python-3.13-m0-v1/venv/bin/python",
            embedding_model=root
            / "models/Qwen/Qwen3-Embedding-0.6B/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
            nli_model=nli_model,
            nli_onnx=nli_model / "onnx/model_quantized.onnx",
            llama_server=root / "runtime/llama.cpp/b11146/llama-server",
            qwen_model=root
            / "models/Qwen/Qwen3-4B-GGUF/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf",
        )

    def validate(self) -> None:
        missing = [
            str(path)
            for path in (
                self.python,
                self.embedding_model / "model.safetensors",
                self.nli_model / "tokenizer.json",
                self.nli_onnx,
                self.llama_server,
                self.qwen_model,
            )
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"frozen M0 model runtime is incomplete: {missing}")


class FrozenModelRuntime:
    def __init__(self, paths: FrozenModelPaths, *, lock_path: Path) -> None:
        paths.validate()
        self._paths = paths
        self._process = SerializedModelProcess(lock_path=lock_path)

    def embed(
        self,
        texts: Iterable[tuple[str, str]],
        *,
        timeout_seconds: float,
    ) -> dict[str, tuple[float, ...]]:
        requests = (
            {"request_id": request_id, "text": text} for request_id, text in texts
        )
        responses = self._process.run(
            (
                str(self._paths.python),
                "-m",
                "src.app.runtime.news_intelligence.model_worker",
                "embedding",
                "--model-path",
                str(self._paths.embedding_model),
                "--max-tokens",
                str(EMBEDDING_MAX_TOKENS),
            ),
            requests,
            timeout_seconds=timeout_seconds,
            environment=self._offline_environment(),
        )
        output: dict[str, tuple[float, ...]] = {}
        for response in responses:
            request_id = response.get("request_id")
            embedding = response.get("embedding")
            if not isinstance(request_id, str) or not isinstance(embedding, list):
                raise ModelProcessError("embedding worker returned an invalid response")
            output[request_id] = tuple(float(value) for value in embedding)
        return output

    def nli(
        self,
        requests: Iterable[tuple[str, str, tuple[str, ...]]],
        *,
        timeout_seconds: float,
    ) -> dict[str, tuple[float, ...]]:
        payloads = []
        for request_id, premise, hypotheses in requests:
            if not 1 <= len(hypotheses) <= NLI_BATCH_SIZE:
                raise ValueError(
                    f"each NLI request must contain 1..{NLI_BATCH_SIZE} hypotheses"
                )
            payloads.append(
                {
                    "request_id": request_id,
                    "premise": premise,
                    "hypotheses": list(hypotheses),
                }
            )
        responses = self._process.run(
            (
                str(self._paths.python),
                "-m",
                "src.app.runtime.news_intelligence.model_worker",
                "nli",
                "--model-path",
                str(self._paths.nli_model),
                "--onnx-path",
                str(self._paths.nli_onnx),
                "--max-tokens",
                str(NLI_MAX_TOKENS),
                "--batch-size",
                str(NLI_BATCH_SIZE),
            ),
            payloads,
            timeout_seconds=timeout_seconds,
            environment=self._offline_environment(),
        )
        output: dict[str, tuple[float, ...]] = {}
        for response in responses:
            request_id = response.get("request_id")
            scores = response.get("entailment_scores")
            if not isinstance(request_id, str) or not isinstance(scores, list):
                raise ModelProcessError("NLI worker returned an invalid response")
            output[request_id] = tuple(float(value) for value in scores)
        return output

    def _offline_environment(self) -> dict[str, str]:
        root = self._paths.runtime_root
        environment = dict(os.environ)
        environment.update(
            {
                "HF_HOME": str(root / "cache/huggingface"),
                "HF_HUB_CACHE": str(root / "cache/huggingface/hub"),
                "TRANSFORMERS_CACHE": str(root / "cache/huggingface/transformers"),
                "TMPDIR": str(root / "tmp"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        return environment
