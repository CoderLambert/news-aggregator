"""Device selection is pure configuration; never loads real weights or Django."""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class EmbeddingDeviceTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('embedding_device_test', ROOT / 'backend/api/services/embedding.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.constructor = Mock(return_value=types.SimpleNamespace(device='cuda:0'))
        self.stub = types.SimpleNamespace(SentenceTransformer=self.constructor)

    def load(self, device):
        with patch.dict(sys.modules, {'sentence_transformers': self.stub}), patch.dict(os.environ, {'EMBEDDING_DEVICE': device}):
            return self.module.EmbeddingService().model

    def test_explicit_cuda_is_forwarded_and_model_is_reused(self):
        first = self.load('cuda')
        self.assertIs(self.load('cuda'), first)
        self.constructor.assert_called_once_with(self.module.MODEL_NAME, device='cuda')

    def test_default_preserves_sentence_transformer_auto_detection(self):
        self.load('')
        self.constructor.assert_called_once_with(self.module.MODEL_NAME, device=None)

    def test_explicit_cpu_remains_available(self):
        self.load('cpu')
        self.constructor.assert_called_once_with(self.module.MODEL_NAME, device='cpu')

    def test_explicit_cuda_failure_does_not_silently_retry_on_cpu(self):
        self.constructor.side_effect = RuntimeError('synthetic CUDA unavailable')
        with self.assertRaises(RuntimeError):
            self.load('cuda')
        self.assertIsNone(self.module.EmbeddingService()._model)
        self.assertFalse(self.module.EmbeddingService.is_loaded())
        self.constructor.assert_called_once_with(self.module.MODEL_NAME, device='cuda')


if __name__ == '__main__':
    unittest.main()
