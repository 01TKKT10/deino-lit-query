
import json
import re
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# 加载数据库
with open('database.json', 'r', encoding='utf-8') as f:
    DATABASE = json.load(f)

@app.route('/')
def index():
    """主页"""
    total = len(DATABASE)
    return render_template('index.html', total=total)

@app.route('/api/search')
def api_search():
    """搜索API — v5 整词匹配 + 交集 + 子串 fallback"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': '请输入查询内容'})

    q = query

    # 精确序号匹配
    if q.isdigit() and q in DATABASE:
        return jsonify({'query': q, 'count': 1, 'results': [DATABASE[q]]})

    all_entries = list(DATABASE.values())
    words = [w for w in q.split() if w]
    if not words:
        return jsonify({'query': q, 'count': 0, 'results': []})

    BATCH_SIZE = 8

    # === 整词匹配函数（\b 词边界）===
    def contains_whole_word(title, word):
        pattern = r'\b' + re.escape(word.lower()) + r'\b'
        return re.search(pattern, title.lower()) is not None

    # === 整词匹配 + 交集 ===
    def build_intersection(limit):
        intersection = None
        last_non_empty = None
        for i in range(limit):
            word = words[i]
            matches = set()
            for e in all_entries:
                if contains_whole_word(e.get('title', '') or '', word):
                    matches.add(e.get('number'))
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

    # 先用前 BATCH_SIZE 个单词（或全部，如果更少）
    result_set = build_intersection(min(len(words), BATCH_SIZE))

    # 检查：交集是否唯一
    if len(result_set) == 1:
        num = list(result_set)[0]
        for e in all_entries:
            if e.get('number') == num:
                return jsonify({'query': q, 'count': 1, 'results': [e]})

    # 不唯一且还有剩余单词 → 逐轮增加
    if len(result_set) > 1 and len(words) > BATCH_SIZE:
        last_non_empty = set(result_set) if len(result_set) > 0 else None
        for i in range(BATCH_SIZE, len(words)):
            word = words[i]
            matches = set()
            for e in all_entries:
                if contains_whole_word(e.get('title', '') or '', word):
                    matches.add(e.get('number'))
            if not matches:
                result_set = last_non_empty or set()
                break
            result_set = result_set & matches
            if len(result_set) == 1:
                num = list(result_set)[0]
                for e in all_entries:
                    if e.get('number') == num:
                        return jsonify({'query': q, 'count': 1, 'results': [e]})
            if len(result_set) > 0:
                last_non_empty = set(result_set)
            if len(result_set) == 0:
                break

    # 整词交集 >1（无法进一步缩小）→ 返回交集内结果
    if len(result_set) > 1:
        results = []
        for e in all_entries:
            if e.get('number') in result_set:
                results.append(e)
                if len(results) >= 30:
                    break
        return jsonify({'query': q, 'count': len(results), 'results': results})

    # === Fallback 1: 子串匹配（所有查询单词子串都匹配）===
    sub_matches = []
    for e in all_entries:
        title_lower = (e.get('title', '') or '').lower()
        if all(w.lower() in title_lower for w in words):
            sub_matches.append(e)
            if len(sub_matches) >= 30:
                break
    if sub_matches:
        return jsonify({'query': q, 'count': len(sub_matches), 'results': sub_matches})

    # === Fallback 2: 作者搜索 ===
    q_lower = q.lower()
    results = []
    for e in all_entries:
        if q_lower in (e.get('authors', '') or '').lower():
            results.append(e)
            if len(results) >= 30:
                break
    if results:
        return jsonify({'query': q, 'count': len(results), 'results': results})

    # === Fallback 3: PMID 精确匹配 ===
    for e in all_entries:
        if e.get('pmid') == q:
            return jsonify({'query': q, 'count': 1, 'results': [e]})

    # === Fallback 4: 摘要全文匹配 ===
    results = []
    for e in all_entries:
        if q_lower in (e.get('abstract', '') or '').lower():
            results.append(e)
            if len(results) >= 30:
                break
    return jsonify({'query': q, 'count': len(results), 'results': results})

@app.route('/api/entry/<num>')
def api_entry(num):
    """获取单篇文献详情"""
    if num in DATABASE:
        return jsonify(DATABASE[num])
    return jsonify({'error': f'未找到编号 {num}'}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
