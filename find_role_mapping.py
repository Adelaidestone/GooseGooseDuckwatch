"""
查找角色ID与名称的映射关系
"""
import re
import json

# 读取HTML文件
html_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\Gaggle Fun 🎮 Next Level Social Gaming游戏具体信息.html'

print("正在读取HTML文件...")
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"文件大小: {len(content)} 字符")

# 查找JSON数据块
print("\n搜索JSON数据...")

# 尝试查找包含role的JSON对象
# 模式1: "role": 数字
role_pattern = r'"role"\s*:\s*(\d+)'
role_matches = re.findall(role_pattern, content)
if role_matches:
    print(f"找到 {len(role_matches)} 个role字段")
    print(f"Role IDs: {sorted(set(role_matches))}")

# 模式2: 查找角色名称附近的数字
known_roles = [
    'Goose', 'Duck', 'Dodo', 'Pigeon', 'Vulture', 'Falcon', 'Morphling',
    'Silencer', 'Canadian Goose', 'Vigilante', 'Birdwatcher', 'Detective',
    'Sheriff', 'Gravy', 'Mechanic', 'Technician', 'Mimic', 'Professional',
    'Hitman', 'Assassin', 'Ninja', 'Spy', 'Cannibal', 'Lover', 'Duellist',
    'Medium', 'Adventurer', 'Celebrity', 'Undertaker', 'Esper', 'Bodyguard',
    'Political', 'Astral', 'Street Urchin', 'Avenger', 'Locksmith',
    'Bounty Hunter', 'Identity Thief', 'Pelican', 'Snitch', 'Warlock',
    'Necromancer', 'Invisibility', 'Serial Killer', 'Demolitionist',
    'Tracker', 'Medic', 'Engineer', 'Mayor', 'Lovers', 'Mortician'
]

print("\n查找角色名称上下文...")
for role in known_roles:
    # 查找角色名称周围的内容
    pattern = rf'.{{0,100}}{role}.{{0,100}}'
    matches = re.findall(pattern, content, re.IGNORECASE)
    if matches:
        print(f"\n{role}:")
        for m in matches[:2]:  # 只显示前2个匹配
            # 清理输出
            clean = m.replace('\n', ' ').strip()
            if len(clean) > 150:
                clean = clean[:150] + '...'
            print(f"  {clean}")

# 查找可能的映射表
print("\n\n查找映射表模式...")
# 模式: 数字: "角色名" 或 "角色名": 数字
mapping_patterns = [
    r'(\d+)\s*:\s*["\']([A-Za-z\s]+)["\']',
    r'["\']([A-Za-z\s]+)["\']\s*:\s*(\d+)',
    r'"id"\s*:\s*(\d+)[^}]*"name"\s*:\s*"([^"]+)"',
]

for pattern in mapping_patterns:
    matches = re.findall(pattern, content)
    if matches:
        print(f"\n模式 {pattern[:30]}... 找到 {len(matches)} 个匹配:")
        for m in matches[:10]:
            print(f"  {m}")

# 提取完整的JSON块
print("\n\n查找完整JSON块...")
json_pattern = r'\{[^{}]*"role"[^{}]*\}'
json_matches = re.findall(json_pattern, content)
if json_matches:
    print(f"找到 {len(json_matches)} 个包含role的JSON块:")
    for m in json_matches[:5]:
        print(f"  {m[:200]}...")
