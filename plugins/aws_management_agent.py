"""AWS operasyonları için hot-loadable marketplace plugin'i."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess  # nosec B404
from collections.abc import Iterable
from typing import Any

from agent.base_agent import BaseAgent


class AWSManagementAgent(BaseAgent):
    """Temel AWS keşif ve operasyon komutlarını çalıştıran marketplace ajanı."""

    ROLE_NAME = "aws_management"

    _COMMAND_MAP = {
        "ec2": ["aws", "ec2", "describe-instances", "--output", "json", "--max-items", "10"],
        "s3": ["aws", "s3api", "list-buckets", "--output", "json"],
        "cloudwatch": [
            "aws",
            "cloudwatch",
            "describe-alarms",
            "--output",
            "json",
            "--max-records",
            "10",
        ],
    }

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "AWS işlemi için görev açıklaması gerekli."

        aws_cli = shutil.which("aws")
        if not aws_cli:
            return (
                "AWS CLI bulunamadı. `aws configure` ile kimlik bilgilerini ayarlayıp "
                "sunucuya AWS CLI kurduktan sonra tekrar deneyin."
            )

        command = self._select_command(prompt)
        if not command:
            supported = ", ".join(sorted(self._COMMAND_MAP))
            return (
                "Desteklenen AWS görevleri: EC2 instance listeleme, S3 bucket listeleme "
                f"ve CloudWatch alarm sorgulama. Anahtar kelimeler: {supported}."
            )

        env = os.environ.copy()
        env.setdefault("AWS_PAGER", "")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            error_text = (exc.stderr or exc.stdout or str(exc)).strip()
            return f"AWS komutu başarısız oldu: {error_text}"
        except Exception as exc:
            return f"AWS komutu çalıştırılamadı: {exc}"

        return self._summarize_output(prompt, completed.stdout)

    def _select_command(self, prompt: str) -> list[str] | None:
        lowered = prompt.lower()
        if any(token in lowered for token in ("ec2", "instance", "instances", "sunucu")):
            return list(self._COMMAND_MAP["ec2"])
        if any(token in lowered for token in ("s3", "bucket", "storage")):
            return list(self._COMMAND_MAP["s3"])
        if any(token in lowered for token in ("cloudwatch", "alarm", "metric")):
            return list(self._COMMAND_MAP["cloudwatch"])
        return None

    @staticmethod
    def _summarize_output(prompt: str, stdout: str) -> str:
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            compact = " ".join((stdout or "").split())
            return f"AWS yanıtı ({prompt}): {compact[:500]}"

        if "Buckets" in payload:
            names = [item.get("Name", "-") for item in payload.get("Buckets", [])]
            preview = ", ".join(names[:8]) if names else "bucket bulunamadı"
            return f"S3 bucket envanteri: {preview}"

        reservations: Iterable[dict[str, Any]] = payload.get("Reservations", []) or []
        instances: list[str] = []
        for reservation in reservations:
            for instance in reservation.get("Instances", []) or []:
                instances.append(
                    f"{instance.get('InstanceId', '?')} ({instance.get('State', {}).get('Name', 'unknown')})"
                )
        if instances:
            return f"EC2 instance envanteri: {', '.join(instances[:8])}"

        alarms = payload.get("MetricAlarms", []) or []
        if alarms:
            summary = ", ".join(
                f"{alarm.get('AlarmName', '?')}={alarm.get('StateValue', 'UNKNOWN')}"
                for alarm in alarms[:8]
            )
            return f"CloudWatch alarmları: {summary}"

        compact = json.dumps(payload, ensure_ascii=False)[:500]
        return f"AWS yanıtı ({prompt}): {compact}"
