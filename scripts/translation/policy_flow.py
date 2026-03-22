from classification.page_classifier import classify_payload_items
from translation.policy_config import TranslationPolicyConfig
from translation.policy_config import build_translation_policy_config
from translation.payload_ops import apply_classification_labels
from translation.payload_ops import apply_narrow_body_text_skip
from translation.payload_ops import apply_after_last_title_skip
from translation.payload_ops import apply_title_skip


def apply_translation_policies(
    *,
    payload: list[dict],
    mode: str,
    classify_batch_size: int,
    api_key: str,
    model: str,
    base_url: str,
    skip_title_translation: bool,
    page_idx: int,
    sci_cutoff_page_idx: int | None,
    sci_cutoff_block_idx: int | None,
    policy_config: TranslationPolicyConfig | None = None,
) -> tuple[int, dict[str, int]]:
    if policy_config is None:
        policy_config = build_translation_policy_config(
            mode=mode,
            skip_title_translation=skip_title_translation,
            sci_cutoff_page_idx=sci_cutoff_page_idx,
            sci_cutoff_block_idx=sci_cutoff_block_idx,
        )

    classified_items = 0
    narrow_body_skipped = apply_narrow_body_text_skip(payload) if policy_config.enable_narrow_body_noise_skip else 0
    skip_summary = {"title_skipped": 0, "tail_skipped": 0, "narrow_body_skipped": narrow_body_skipped}

    if policy_config.mode == "precise":
        labels = classify_payload_items(
            payload,
            api_key=api_key,
            model=model,
            base_url=base_url,
            batch_size=classify_batch_size,
        )
        classified_items = apply_classification_labels(payload, labels)

    if policy_config.enable_after_last_title_cutoff:
        title_skipped = apply_title_skip(payload)
        tail_skipped = apply_after_last_title_skip(
            payload,
            page_idx=page_idx,
            cutoff_page_idx=policy_config.sci_cutoff_page_idx,
            cutoff_block_idx=policy_config.sci_cutoff_block_idx,
        )
        skip_summary = {
            "title_skipped": title_skipped,
            "tail_skipped": tail_skipped,
            "narrow_body_skipped": narrow_body_skipped,
        }
    elif policy_config.enable_title_skip:
        skip_summary = {
            "title_skipped": apply_title_skip(payload),
            "tail_skipped": 0,
            "narrow_body_skipped": skip_summary["narrow_body_skipped"],
        }

    return classified_items, skip_summary
