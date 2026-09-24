#!/usr/bin/env python3
"""Standalone worker: loads a local diffusion model and generates one image, then exits.

Run as a separate OS process (never imported) so a hang here can never affect Jervis itself. torch's MPS/CUDA calls
can hold Python's GIL for a long time, or the GPU driver itself can stall, in a way a thread-based timeout cannot
interrupt — only killing the whole process (subprocess.run(..., timeout=...) in images.py) can guarantee that.

Usage: local_image_worker.py <model> <device> <output_path> <prompt...>
Exit 0 and a PNG written to output_path on success; exit 1 and a message on stderr on failure.
"""
import sys


def main() -> int:
    if len(sys.argv) < 5:
        print("usage: local_image_worker.py <model> <device> <output_path> <prompt...>", file=sys.stderr)
        return 2
    model, device, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
    prompt = " ".join(sys.argv[4:])
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
        pipe = AutoPipelineForText2Image.from_pretrained(model, dtype=torch.float32, safety_checker=None)
        pipe = pipe.to(device)
        # sd-turbo (the default model) is a distilled model: it wants few steps and no guidance scale, and was
        # trained at 512x512 — going higher tends to produce broken, repeated compositions rather than more detail.
        image = pipe(prompt=prompt, num_inference_steps=4, guidance_scale=0.0, height=512, width=512).images[0]
        image.save(output_path, format="PNG")
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
