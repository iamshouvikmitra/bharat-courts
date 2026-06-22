# CAPTCHA solvers

The live portals are Securimage-CAPTCHA gated. Solving is pluggable: implement the
`CaptchaSolver` ABC, or use one of the bundled solvers. See the
[CAPTCHA guide](../guides/captcha.md).

## CaptchaSolver (base class)

::: bharat_courts.captcha.base.CaptchaSolver

## OCRCaptchaSolver

::: bharat_courts.captcha.ocr.OCRCaptchaSolver

## ONNXCaptchaSolver

::: bharat_courts.captcha.onnx.ONNXCaptchaSolver

## ManualCaptchaSolver

::: bharat_courts.captcha.manual.ManualCaptchaSolver
