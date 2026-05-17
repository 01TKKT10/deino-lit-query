
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
    """搜索API — 单词独立检索 + 投票计数 + 逐轮核对唯一性"""
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

    # === 投票计数 + 唯一性核对 ===
    from collections import defaultdict
    vote_map = defaultdict(lambda: {'entry': None, 'count': 0})
    BATCH_SIZE = 8

    def add_votes(word):
        w = word.lower()
        for e in all_entries:
            title = (e.get('title', '') or '').lower()
            if w in title:
                num = e.get('number')
                vote_map[num]['entry'] = e
                vote_map[num]['count'] += 1

    def find_unique_max():
        if not vote_map:
            return None
        max_count = max(v['count'] for v in vote_map.values())
        max_items = [v for v in vote_map.values() if v['count'] == max_count]
        return max_items[0] if len(max_items) == 1 else None

    def get_top_n(n):
        sorted_items = sorted(vote_map.values(), key=lambda x: x['count'], reverse=True)
        return [v['entry'] for v in sorted_items[:n]]

    # 先处理前8个单词（或全部单词，取最小值）
    initial_count = min(len(words), BATCH_SIZE)
    for i in range(initial_count):
        add_votes(words[i])

    # 核对：最高票数是否唯一
    winner = find_unique_max()
    if winner:
        return jsonify({
            'query': q,
            'count': 1,
            'results': [winner['entry']]
        })

    # 不唯一 → 逐轮增加第9个、第10个...单词
    for i in range(BATCH_SIZE, len(words)):
        add_votes(words[i])
        winner = find_unique_max()
        if winner:
            return jsonify({
                'query': q,
                'count': 1,
                'results': [winner['entry']]
            })

    # 所有单词用完仍不唯一 → 按票数排序，返回前30
    results = get_top_n(30)
    if results:
        return jsonify({
            'query': q,
            'count': len(results),
            'results': results
        })

    # === Fallback 搜索 ===
    q_lower = q.lower()
    for e in all_entries:
        if q_lower in (e.get('authors', '') or '').lower():
            results.append(e)
            if len(results) >= 30:
                break

    if not results:
        for e in all_entries:
            if e.get('pmid') == q:
                results.append(e)
                break

    if not results:
        for e in all_entries:
            if q_lower in (e.get('abstract', '') or '').lower():
                results.append(e)
                if len(results) >= 30:
                    break

    return jsonify({
        'query': q,
        'count': len(results),
        'results': results
    })

@app.route('/api/entry/<num>')
def api_entry(num):
    """获取单篇文献详情"""
    if num in DATABASE:
        return jsonify(DATABASE[num])
    return jsonify({'error': f'未找到编号 {num}'}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
