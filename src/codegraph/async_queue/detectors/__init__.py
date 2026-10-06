"""Detectors for asynchronous message brokers and task dispatchers."""
from __future__ import annotations

import ast

from codegraph.async_queue.detectors.celery import detect_celery
from codegraph.async_queue.detectors.kafka import detect_kafka
from codegraph.async_queue.detectors.rabbitmq import detect_rabbitmq
from codegraph.async_queue.detectors.redis import detect_redis
from codegraph.async_queue.detectors.sqs import detect_sqs
from codegraph.async_queue.models import AsyncConsumerRecord, AsyncProducerRecord

ALL_DETECTORS = [
    detect_celery,
    detect_kafka,
    detect_sqs,
    detect_rabbitmq,
    detect_redis,
]


def run_all_detectors(
    tree: ast.AST,
    content: str,
    file_path: str,
    module_name: str,
) -> tuple[list[AsyncProducerRecord], list[AsyncConsumerRecord]]:
    """Run all framework detectors on parsed Python AST."""
    all_producers: list[AsyncProducerRecord] = []
    all_consumers: list[AsyncConsumerRecord] = []

    for detector in ALL_DETECTORS:
        prods, cons = detector(tree, content, file_path, module_name)
        all_producers.extend(prods)
        all_consumers.extend(cons)

    return all_producers, all_consumers


__all__ = [
    "ALL_DETECTORS",
    "detect_celery",
    "detect_kafka",
    "detect_rabbitmq",
    "detect_redis",
    "detect_sqs",
    "run_all_detectors",
]
