import re
import unicodedata


def is_batch_approval(text):
    text = unicodedata.normalize('NFKC', text or '').casefold()
    text = re.sub(r'[\s\ufe0f\U0001f3fb-\U0001f3ff]', '', text)
    return text.strip('。.!！') in {'以上ok', '以上👌'}


def missing_approvals(rec, tech_keywords):
    missing = []
    if not rec.get('first_approved_msg_id'):
        missing.append('first')
    if any(k in rec.get('org_unit', '') for k in tech_keywords):
        if (not rec.get('second_approved_msg_id')
                or rec.get('second_approved_msg_id', 0) <= rec.get('first_approved_msg_id', 0)):
            missing.append('second')
    return missing


def recover_approvals(rec, messages, authors, first, second, is_approval):
    """仅从明确引用本Offer的历史同意消息补齐证据，不猜测普通群聊归属。"""
    result = dict(rec)
    by_id = {m.id: m for m in messages}
    roots = {rec.get(k) for k in ('offer_confirm_msg_id', 'second_review_msg_id', 'final_review_msg_id')}
    roots.discard(None)
    def belongs(message):
        target = getattr(message, 'reply_to_msg_id', None)
        seen = set()
        while target and target not in seen:
            if target in roots:
                return True
            seen.add(target)
            parent = by_id.get(target)
            target = getattr(parent, 'reply_to_msg_id', None)
        return False
    for msg in sorted(messages, key=lambda m: m.id):
        if msg.id <= rec['offer_confirm_msg_id'] or not belongs(msg) or not is_approval(msg.raw_text):
            continue
        author = authors.get(msg.sender_id, '')
        if author == first and not result.get('first_approved_msg_id'):
            result['first_approved_msg_id'] = msg.id
        elif (author == second and result.get('first_approved_msg_id', msg.id) < msg.id
              and rec.get('second_review_msg_id', msg.id) < msg.id
              and not result.get('second_approved_msg_id')):
            result['second_approved_msg_id'] = msg.id
    return result
