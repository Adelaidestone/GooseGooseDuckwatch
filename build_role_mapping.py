"""
分析现有的JSON数据和HTML数据，建立游戏角色ID与名称的映射关系
"""
import json
import re

# 读取捕获的API数据
api_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\captured_api_data.json'
html_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\Gaggle Fun 🎮 Next Level Social Gaming游戏具体信息.html'

print("=" * 60)
print("🦆 分析角色ID映射关系")
print("=" * 60)

# 1. 从API数据提取 nickname -> role_id 映射
print("\n📄 读取API数据...")
with open(api_file, 'r', encoding='utf-8') as f:
    api_data = json.load(f)

# 从所有match中提取player数据
api_players = {}  # {nickname: role_id}
for match in api_data:
    if 'data' in match and 'playerData' in match['data']:
        for player_id, player_info in match['data']['playerData'].items():
            nickname = player_info.get('nickname', '')
            role_id = player_info.get('role', 0)
            if nickname and role_id:
                api_players[nickname] = role_id

print(f"找到 {len(api_players)} 个玩家的角色ID:")
for name, role_id in sorted(api_players.items(), key=lambda x: x[1]):
    print(f"  {role_id}: {name}")

# 2. 从HTML提取 player-name -> player-role 映射
print("\n📄 读取HTML数据...")
with open(html_file, 'r', encoding='utf-8') as f:
    html_content = f.read()

# 查找table-row中的player-name和player-role对
# 模式: 找到player-name和player-role相邻出现的情况
pattern = r'class="player-name"[^>]*>([^<]+)</.*?class="player-role"[^>]*>([^<]+)<'
html_players = {}  # {player_name: role_name}
matches = re.findall(pattern, html_content, re.DOTALL)
for name, role in matches:
    name = name.strip()
    role = role.strip()
    if name and role and role != '-':
        html_players[name] = role

print(f"找到 {len(html_players)} 个玩家的角色名:")
for name, role in sorted(html_players.items()):
    print(f"  {name}: {role}")

# 3. 匹配nickname建立 role_id -> role_name 映射
print("\n" + "=" * 60)
print("🔗 建立角色ID与名称的映射关系")
print("=" * 60)

role_mapping = {}  # {role_id: role_name}
matched_players = []

for nickname, role_id in api_players.items():
    if nickname in html_players:
        role_name = html_players[nickname]
        if role_id not in role_mapping:
            role_mapping[role_id] = role_name
            matched_players.append(f"{nickname}: {role_id} -> {role_name}")
        elif role_mapping[role_id] != role_name:
            print(f"  ⚠️ 冲突: {role_id} -> {role_mapping[role_id]} vs {role_name}")

print(f"\n通过玩家昵称匹配:")
for match in matched_players:
    print(f"  ✓ {match}")

# 4. 补充从role-icons获取的英文角色名
print("\n📋 从role-icons提取英文角色名:")
icon_pattern = r'role-icons/([A-Za-z]+)-\d+x\d+\.png'
icons = set(re.findall(icon_pattern, html_content))
for icon in sorted(icons):
    print(f"  {icon}")

# 5. 已知的中英文角色名对应关系（从前端显示推断）
known_mapping = {
    '爆炸王': 'Demolitionist',
    '加拿大鹅': 'Canadian Goose',
    '殡仪员': 'Mortician',
    '猎鹰': 'Falcon',
    '鸽子': 'Pigeon',
    '星界行者': 'Astral',
    '传教士': 'Preacher',
    '生存主义者': 'Survivalist',
    '正义使者': 'Vigilante',
    '士兵': 'Soldier',
    '呆呆鸟': 'Dodo',
    '秃鹫': 'Vulture',
    '肉汁': 'Gravy',
    '间谍': 'Spy',
    '警长': 'Sheriff',
    '网红': 'Celebrity',
}

# 6. 输出最终映射表
print("\n" + "=" * 60)
print("📊 最终角色ID映射表")
print("=" * 60)

final_mapping = {}
for role_id, role_name_cn in sorted(role_mapping.items()):
    role_name_en = known_mapping.get(role_name_cn, role_name_cn)
    final_mapping[role_id] = {
        'cn': role_name_cn,
        'en': role_name_en
    }
    print(f"  {role_id}: {role_name_cn} ({role_name_en})")

# 保存映射表
output_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\game_role_id_mapping.json'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(final_mapping, f, ensure_ascii=False, indent=2)
print(f"\n✅ 映射表已保存到: {output_file}")

# 7. 显示尚未映射的role ID
print("\n⚠️ 尚未映射的role ID:")
all_role_ids = set(api_players.values())
mapped_ids = set(role_mapping.keys())
unmapped = all_role_ids - mapped_ids
for role_id in sorted(unmapped):
    players = [n for n, r in api_players.items() if r == role_id]
    print(f"  {role_id}: (玩家: {', '.join(players)})")
