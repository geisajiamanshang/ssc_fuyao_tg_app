def select_pending(items, states, reviewer_id, code, approval_id, reply_id=None):
    """每个审批事件最多消费一条；引用不匹配时绝不回退到其他草稿。"""
    items = list(items)
    if any(r.get('approval_msg_id') == approval_id for r in items):
        return None
    eligible = [r for r in items
                if r.get('status') == 'pending'
                and r['draft_id'] < approval_id
                and r.get('review_chat_id') == reviewer_id
                and str(r.get('approval_code', '1')) == code
                and (reply_id is None or r['draft_id'] == reply_id)
                and states.get(r['candidate'], {}).get('stage') == r['expected_stage']]
    return max(eligible, key=lambda r: r['draft_id'], default=None)
