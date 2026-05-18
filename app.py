import json
import re
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# 加载数据库（格式: {number_str: entry_dict}）
with open('database.json', 'r', encoding='utf-8') as f:
    DATABASE = json.load(f)

# 所有条目列表（用于遍历）
ALL_ENTRIES = list(DATABASE.values())

# ═══════════════════════════════════════════════════════
# V8 引擎配置与常量
# ═══════════════════════════════════════════════════════

STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
    'may', 'might', 'can', 'shall', 'must', 'lt', 'gt',
    'of', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by',
    'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after',
    'above', 'below', 'between', 'among', 'this', 'that', 'these', 'those',
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
    'as', 'if', 'so', 'than', 'too', 'very', 'just', 'now', 'then', 'here',
    'there', 'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both',
    'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same'
}

BATCH_SIZE = 8
UNIQUE_THRESHOLD = 15


# ═══════════════════════════════════════════════════════
# V8 查询清洗与辅助函数
# ═══════════════════════════════════════════════════════

def clean_query(query):
    """
    V8 查询清洗：从查询字符串中提取标题词、期刊词、年份。
    兼容普通搜索查询和 PDF 文件名格式。
    """
    q = query.strip()

    # 1. 去除 UUID、前导数字
    q = re.sub(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}_?', '', q, flags=re.I)
    q = re.sub(r'^\d+[\-_\s]+', '', q)
    q = re.sub(r'_', ' ', q)
    q = re.sub(r'(?<=[a-zA-Z])\-(?=[a-zA-Z])', ' ', q)

    # 2. 提取年份 (19xx 或 20xx)
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', q)
    year = int(year_match.group(1)) if year_match else None

    # 3. 提取期刊名 (Source 和 SO 之间)
    journal_words = []
    source_match = re.search(r'\bSource\b', q, re.I)
    so_match = re.search(r'\bSO\s+\d{4}\b', q, re.I)
    if source_match and so_match:
        journal_raw = q[source_match.end():so_match.start()].strip()
        for w in journal_raw.split():
            w_clean = re.sub(r'[^a-zA-Z]', '', w)
            if w_clean and len(w_clean) >= 2 and w_clean.lower() not in STOP_WORDS:
                journal_words.append(w_clean)

    # 4. 清理 Source 及之后所有内容
    if source_match:
        q = q[:source_match.start()]

    # 5. 再次清理 SO YYYY
    so_match2 = re.search(r'\bSO\s+\d{4}\b', q, re.I)
    if so_match2:
        q = q[:so_match2.start()]

    # 6. 清理 HTML 实体残留
    q = re.sub(r'\blt\b|\bgt\b|\bi\b|\bb\b', '', q, flags=re.I)

    # 7. 空格拆分 + 标点剥离
    words = q.split()
    cleaned_words = []
    for word in words:
        while word and word[-1] in ',.;:!?':
            word = word[:-1]
        while word and word[0] in ',.;:!?':
            word = word[1:]
        if word:
            cleaned_words.append(word)
    q = ' '.join(cleaned_words)

    # 8. 停用词过滤
    result = [w for w in q.split() if w.lower() not in STOP_WORDS]

    return result, journal_words, year


def contains_whole_word(title, word):
    if not title or not word:
        return False
    try:
        pattern = r'\b' + re.escape(word.lower()) + r'\b'
        return re.search(pattern, title.lower()) is not None
    except re.error:
        return False


def contains_prefix_word(title, word):
    if not title or not word:
        return False
    try:
        pattern = r'\b' + re.escape(word.lower()) + r'\w*\b'
        return re.search(pattern, title.lower()) is not None
    except re.error:
        return False


def contains_substring(title, word):
    if not title or not word:
        return False
    return word.lower() in title.lower()


def get_word_positions(title, query_words, match_fn):
    title_lower = title.lower()
    positions = []
    for word in query_words:
        if not match_fn(title, word):
            continue
        word_lower = word.lower()
        pattern = r'\b' + re.escape(word_lower) + r'\b'
        if len(word) <= 4:
            pattern = r'\b' + re.escape(word_lower) + r'\w*\b'
        for m in re.finditer(pattern, title_lower):
            positions.append((word, m.start(), m.end()))
            break
    return positions


def calc_phrase_bonus(title, words):
    title_lower = title.lower()
    bonus = 0
    for i in range(len(words) - 1):
        phrase = f"{words[i].lower()} {words[i+1].lower()}"
        if phrase in title_lower:
            bonus += 12
    for i in range(len(words) - 2):
        phrase = f"{words[i].lower()} {words[i+1].lower()} {words[i+2].lower()}"
        if phrase in title_lower:
            bonus += 20
    return min(bonus, 40)


def calc_order_score(title, query_words, match_fn):
    positions = get_word_positions(title, query_words, match_fn)
    if len(positions) <= 1:
        return 0
    starts = [p[1] for p in positions]
    dp = [1] * len(starts)
    for i in range(1, len(starts)):
        for j in range(i):
            if starts[i] > starts[j]:
                dp[i] = max(dp[i], dp[j] + 1)
    order_score = (max(dp) / len(query_words)) * 30

    consecutive_bonus = 0
    for i in range(1, len(positions)):
        gap = positions[i][1] - positions[i-1][2]
        if gap == 0:
            consecutive_bonus += 3
        elif gap <= 1:
            consecutive_bonus += 10
        elif gap <= 5:
            consecutive_bonus += 7
        elif gap <= 15:
            consecutive_bonus += 5
        elif gap <= 30:
            consecutive_bonus += 2
    return round(order_score + min(consecutive_bonus, 30))


def calc_journal_score(entry_journal, journal_words):
    if not journal_words or not entry_journal:
        return 0
    matched = sum(1 for w in journal_words if contains_prefix_word(entry_journal, w))
    if matched == 0:
        return 0
    score = matched * 12
    if matched == len(journal_words):
        score += 15
    return min(score, 40)


def calc_year_score(entry_year, query_year):
    if query_year is None or entry_year is None:
        return 0
    return 25 if entry_year == query_year else 0


def calc_score(title, words, match_fn, journal_words=None, entry_journal=None,
               query_year=None, entry_year=None):
    title_lower = title.lower()
    score = 0
    matched_count = 0
    case_sensitive_match = False

    for word in words:
        if match_fn(title, word):
            matched_count += 1
        if word in title:
            case_sensitive_match = True

    if words:
        score += (matched_count / len(words)) * 50

    if matched_count > 0:
        positions = get_word_positions(title, words, match_fn)
        if positions:
            half = len(title_lower) / 2
            if all(p[1] < half for p in positions):
                score += 25
            elif any(p[1] < half for p in positions):
                score += 15
            else:
                score += 5

    q_joined = ' '.join(words).lower()
    if q_joined in title_lower:
        score += 25
    if case_sensitive_match:
        score += 5

    score += calc_order_score(title, words, match_fn)
    score += calc_phrase_bonus(title, words)

    if matched_count > 0 and words:
        covered_chars = sum(len(w) for w in words if match_fn(title, w))
        title_len = len(title_lower.replace(' ', ''))
        if title_len > 0:
            score += round(covered_chars / title_len * 20)

    if journal_words and entry_journal:
        score += calc_journal_score(entry_journal, journal_words)

    if query_year is not None and entry_year is not None:
        score += calc_year_score(entry_year, query_year)

    return round(score)


# ═══════════════════════════════════════════════════════
# 交集构建
# ═══════════════════════════════════════════════════════

def build_intersection_strict(entries, words, limit):
    intersection = None
    last_non_empty = None
    failed_words = []
    for i in range(limit):
        word = words[i]
        matches = set()
        for e in entries:
            if contains_whole_word(e.get('title', '') or '', word):
                matches.add(str(e.get('number')))
        if not matches:
            failed_words.append(word)
            if intersection is not None:
                return last_non_empty or set(), failed_words
            continue
        if intersection is None:
            intersection = matches
        else:
            intersection = intersection & matches
        if len(intersection) == 1:
            return intersection, failed_words
        if len(intersection) > 0:
            last_non_empty = set(intersection)
    return intersection or set(), failed_words


def build_intersection_all_fuzzy(entries, words, limit):
    intersection = None
    last_non_empty = None
    for i in range(limit):
        word = words[i]
        matches = set()
        for e in entries:
            if contains_prefix_word(e.get('title', '') or '', word):
                matches.add(str(e.get('number')))
        if not matches:
            return last_non_empty or set()
        if intersection is None:
            intersection = matches
        else:
            intersection = intersection & matches
        if len(intersection) == 1:
            return intersection
        if len(intersection) > 0:
            last_non_empty = set(intersection)
    return intersection or set()


# ═══════════════════════════════════════════════════════
# Flask 路由
# ═══════════════════════════════════════════════════════

@app.route('/')
def index():
    """主页"""
    total = len(DATABASE)
    return render_template('index.html', total=total)


@app.route('/api/search')
def api_search():
    """
    搜索API — v8 增强匹配引擎
    返回带 _score 字段的文献列表，前端可显示匹配度
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': '请输入查询内容'})

    # 精确序号匹配
    if query.isdigit() and query in DATABASE:
        entry = dict(DATABASE[query])
        entry['_score'] = 100
        entry['_match_status'] = 'exact_number'
        return jsonify({'query': query, 'count': 1, 'results': [entry]})

    # V8 查询清洗
    words, journal_words, year = clean_query(query)
    if not words and not journal_words and year is None:
        return jsonify({'query': query, 'count': 0, 'results': []})

    all_entries = ALL_ENTRIES

    # ═══════════════════════════════════════════
    # Phase 1: 严格整词交集
    # ═══════════════════════════════════════════
    strict_set, failed_words = build_intersection_strict(
        all_entries, words, min(len(words), BATCH_SIZE))

    # 还有剩余单词，继续严格交集
    if len(strict_set) > 1 and len(words) > BATCH_SIZE:
        last_non_empty = set(strict_set) if strict_set else None
        for i in range(BATCH_SIZE, len(words)):
            word = words[i]
            matches = set()
            for e in all_entries:
                if contains_whole_word(e.get('title', '') or '', word):
                    matches.add(str(e.get('number')))
            if not matches:
                strict_set = last_non_empty or set()
                break
            strict_set = strict_set & matches
            if len(strict_set) == 1:
                break
            if strict_set:
                last_non_empty = set(strict_set)

    if len(strict_set) == 1:
        num = list(strict_set)[0]
        for e in all_entries:
            if str(e.get('number')) == num:
                entry = dict(e)
                entry['_score'] = 100
                entry['_match_status'] = 'unique_match_strict'
                return jsonify({'query': query, 'count': 1, 'results': [entry]})

    # ═══════════════════════════════════════════
    # Phase 2: 严格交集为空 → 强制前缀模糊交集
    # ═══════════════════════════════════════════
    if len(strict_set) == 0:
        fuzzy_set = build_intersection_all_fuzzy(
            all_entries, words, min(len(words), BATCH_SIZE))
    elif len(strict_set) > 1 and failed_words:
        fuzzy_set = build_intersection_all_fuzzy(
            all_entries, words, min(len(words), BATCH_SIZE))
    else:
        fuzzy_set = set()

    if len(fuzzy_set) == 1:
        num = list(fuzzy_set)[0]
        for e in all_entries:
            if str(e.get('number')) == num:
                entry = dict(e)
                status = 'unique_match_fuzzy' if failed_words else 'unique_match_strict'
                entry['_score'] = 95
                entry['_match_status'] = status
                return jsonify({'query': query, 'count': 1, 'results': [entry]})

    if fuzzy_set:
        strict_set = fuzzy_set

    # ═══════════════════════════════════════════
    # Phase 3: 综合评分排序
    # ═══════════════════════════════════════════
    if len(strict_set) > 1:
        match_fn = contains_prefix_word if failed_words else contains_whole_word
        scored = []
        for e in all_entries:
            if str(e.get('number')) in strict_set:
                s = calc_score(
                    e.get('title', '') or '', words, match_fn,
                    journal_words, e.get('journal'),
                    year, e.get('year')
                )
                entry = dict(e)
                entry['_score'] = s
                entry['_match_status'] = 'multi_match'
                scored.append((entry, s))
        scored.sort(key=lambda x: x[1], reverse=True)

        # 分差阈值自动唯一化
        if len(scored) >= 2 and (scored[0][1] - scored[1][1]) >= UNIQUE_THRESHOLD:
            top = scored[0][0]
            top['_match_status'] = 'unique_match_fuzzy' if failed_words else 'unique_match_strict'
            return jsonify({'query': query, 'count': 1, 'results': [top]})

        results = [x[0] for x in scored[:30]]
        return jsonify({'query': query, 'count': len(results), 'results': results})

    # ═══════════════════════════════════════════
    # Fallback: 子串匹配
    # ═══════════════════════════════════════════
    sub_matches = []
    for e in all_entries:
        title_lower = (e.get('title', '') or '').lower()
        if all(w.lower() in title_lower for w in words):
            sub_matches.append(e)

    if sub_matches:
        scored = []
        for e in sub_matches:
            s = calc_score(
                e.get('title', '') or '', words, contains_substring,
                journal_words, e.get('journal'),
                year, e.get('year')
            )
            entry = dict(e)
            entry['_score'] = s
            entry['_match_status'] = 'substring_fallback'
            scored.append((entry, s))
        scored.sort(key=lambda x: x[1], reverse=True)

        if len(scored) >= 2 and (scored[0][1] - scored[1][1]) >= UNIQUE_THRESHOLD:
            top = scored[0][0]
            top['_match_status'] = 'unique_match_fallback'
            return jsonify({'query': query, 'count': 1, 'results': [top]})

        results = [x[0] for x in scored[:30]]
        return jsonify({'query': query, 'count': len(results), 'results': results})

    # ═══════════════════════════════════════════
    # Fallback 2: 作者搜索
    # ═══════════════════════════════════════════
    q_lower = query.lower()
    results = []
    for e in all_entries:
        if q_lower in (e.get('authors', '') or '').lower():
            entry = dict(e)
            entry['_score'] = 10
            entry['_match_status'] = 'author_match'
            results.append(entry)
            if len(results) >= 30:
                break
    if results:
        return jsonify({'query': query, 'count': len(results), 'results': results})

    # ═══════════════════════════════════════════
    # Fallback 3: PMID 精确匹配
    # ═══════════════════════════════════════════
    for e in all_entries:
        if e.get('pmid') == query:
            entry = dict(e)
            entry['_score'] = 100
            entry['_match_status'] = 'pmid_match'
            return jsonify({'query': query, 'count': 1, 'results': [entry]})

    # ═══════════════════════════════════════════
    # Fallback 4: 摘要全文匹配
    # ═══════════════════════════════════════════
    results = []
    for e in all_entries:
        if q_lower in (e.get('abstract', '') or '').lower():
            entry = dict(e)
            entry['_score'] = 5
            entry['_match_status'] = 'abstract_match'
            results.append(entry)
            if len(results) >= 30:
                break
    return jsonify({'query': query, 'count': len(results), 'results': results})


@app.route('/api/entry/<num>')
def api_entry(num):
    """获取单篇文献详情"""
    if num in DATABASE:
        return jsonify(DATABASE[num])
    return jsonify({'error': f'未找到编号 {num}'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
