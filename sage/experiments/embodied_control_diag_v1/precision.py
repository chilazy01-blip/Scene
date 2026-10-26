"""Keep the official model and processor; vary only numerical execution."""
import torch


def configure_numeric_execution():
    torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision('highest')


def infer_action(policy, post, batch, mode):
    """Return physical-unit action and its pre-unnormalization prediction."""
    with torch.inference_mode():
        if mode in ('legacy_bf16', 'bf16_fp32_post'):
            with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
                normalized = policy.select_action(batch)
                if mode == 'legacy_bf16':
                    action = post(normalized)
            if mode == 'bf16_fp32_post':
                with torch.autocast(device_type='cuda', enabled=False):
                    action = post(normalized.float())
        elif mode == 'fp32':
            with torch.autocast(device_type='cuda', enabled=False):
                normalized = policy.select_action(batch)
                action = post(normalized.float())
        else:
            raise ValueError(mode)
    return action, normalized
