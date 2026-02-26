"""Tests for device_info: detect_device and get_device_string."""

from unittest.mock import patch

# Heavy deps (torch) are stubbed in conftest.py.
import device_info


class TestDetectDevice:
    def setup_method(self):
        """Reset the global cache between tests."""
        device_info._cached_info = None

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4090")
    def test_cuda_detected(self, mock_name, mock_cuda):
        result = device_info.detect_device()
        assert result["device_type"] == "cuda"
        assert result["gpu_available"] is True
        assert result["turbo_supported"] is True
        assert result["device_name"] == "NVIDIA RTX 4090"

    @patch("torch.cuda.is_available", return_value=False)
    @patch("torch.backends.mps.is_available", return_value=True)
    def test_mps_detected(self, mock_mps, mock_cuda):
        result = device_info.detect_device()
        assert result["device_type"] == "mps"
        assert result["gpu_available"] is True
        assert result["device_name"] == "Apple Silicon GPU"

    @patch("torch.cuda.is_available", return_value=False)
    @patch("torch.backends.mps.is_available", return_value=False)
    def test_cpu_fallback(self, mock_mps, mock_cuda):
        result = device_info.detect_device()
        assert result["device_type"] == "cpu"
        assert result["gpu_available"] is False
        assert result["turbo_supported"] is False

    @patch("torch.cuda.is_available", return_value=False)
    @patch("torch.backends.mps.is_available", return_value=True)
    def test_result_is_cached(self, mock_mps, mock_cuda):
        first = device_info.detect_device()
        mock_cuda.reset_mock()
        mock_mps.reset_mock()
        second = device_info.detect_device()
        assert first is second
        mock_cuda.assert_not_called()
        mock_mps.assert_not_called()

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.backends.mps.is_available", return_value=True)
    @patch("torch.cuda.get_device_name", return_value="GPU")
    def test_cuda_takes_priority_over_mps(self, mock_name, mock_mps, mock_cuda):
        result = device_info.detect_device()
        assert result["device_type"] == "cuda"


class TestGetDeviceString:
    def setup_method(self):
        device_info._cached_info = None

    @patch("torch.cuda.is_available", return_value=False)
    @patch("torch.backends.mps.is_available", return_value=True)
    def test_returns_device_type_string(self, mock_mps, mock_cuda):
        assert device_info.get_device_string() == "mps"

    @patch("torch.cuda.is_available", return_value=False)
    @patch("torch.backends.mps.is_available", return_value=False)
    def test_returns_cpu_when_no_gpu(self, mock_mps, mock_cuda):
        assert device_info.get_device_string() == "cpu"
