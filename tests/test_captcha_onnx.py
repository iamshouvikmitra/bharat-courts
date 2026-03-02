"""Tests for ONNX CAPTCHA solver."""

from unittest.mock import MagicMock

from bharat_courts.captcha.onnx import _CHARSET, _ctc_greedy_decode


class TestCTCGreedyDecode:
    def test_simple_decode(self):
        # Simulate logits where class 1 (digit '0') is highest at each timestep
        # 6 timesteps, each with blank + 62 classes
        num_classes = 1 + len(_CHARSET)
        logits = []
        for i in range(6):
            row = [0.0] * num_classes
            # Set class i+1 (chars '0','1','2','3','4','5') as highest
            row[i + 1] = 10.0
            logits.append(row)
        result = _ctc_greedy_decode(logits)
        assert result == "012345"

    def test_blank_removal(self):
        num_classes = 1 + len(_CHARSET)
        logits = []
        # timestep 1: class 1 ('0')
        row = [0.0] * num_classes
        row[1] = 10.0
        logits.append(row)
        # timestep 2: blank
        row = [10.0] + [0.0] * len(_CHARSET)
        logits.append(row)
        # timestep 3: class 2 ('1')
        row = [0.0] * num_classes
        row[2] = 10.0
        logits.append(row)
        result = _ctc_greedy_decode(logits)
        assert result == "01"

    def test_repeat_collapse(self):
        num_classes = 1 + len(_CHARSET)
        logits = []
        # Three timesteps all predicting class 1 ('0') — should collapse to single '0'
        for _ in range(3):
            row = [0.0] * num_classes
            row[1] = 10.0
            logits.append(row)
        result = _ctc_greedy_decode(logits)
        assert result == "0"

    def test_empty_logits(self):
        assert _ctc_greedy_decode([]) == ""

    def test_all_blanks(self):
        logits = [[10.0] + [0.0] * len(_CHARSET)] * 5
        assert _ctc_greedy_decode(logits) == ""


class TestONNXCaptchaSolver:
    def _make_solver_with_mock_session(self, logits):
        """Create an ONNXCaptchaSolver with a mocked session and preprocessor."""
        import numpy as np

        from bharat_courts.captcha.onnx import ONNXCaptchaSolver

        solver = ONNXCaptchaSolver.__new__(ONNXCaptchaSolver)
        solver._model_path = None

        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [MagicMock(name="input")]
        mock_session.run.return_value = [logits]
        solver._session = mock_session

        # Mock _preprocess to avoid needing a real image
        dummy_input = np.zeros((1, 1, 70, 200), dtype=np.float32)
        solver._preprocess = MagicMock(return_value=dummy_input)
        return solver

    async def test_solve_returns_empty_on_wrong_length(self):
        import numpy as np

        num_classes = 1 + len(_CHARSET)
        # 3 timesteps = 3 chars (not 6)
        logits = np.zeros((1, 3, num_classes), dtype=np.float32)
        for i in range(3):
            logits[0, i, i + 1] = 10.0

        solver = self._make_solver_with_mock_session(logits)
        result = await solver.solve(b"fake-png-bytes")
        assert result == ""  # Wrong length, returns empty

    async def test_solve_returns_text_on_correct_length(self):
        import numpy as np

        num_classes = 1 + len(_CHARSET)
        # 6 timesteps = 6 chars
        logits = np.zeros((1, 6, num_classes), dtype=np.float32)
        for i in range(6):
            logits[0, i, i + 1] = 10.0

        solver = self._make_solver_with_mock_session(logits)
        result = await solver.solve(b"fake-png-bytes")
        assert result == "012345"
