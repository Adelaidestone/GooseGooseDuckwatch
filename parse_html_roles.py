"""
从保存的HTML文件中提取player-name和player-role信息
"""
import re

html_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\Gaggle Fun 🎮 Next Level Social Gaming游戏具体信息.html'

print("读取HTML文件...")
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"文件大小: {len(content):,} 字符\n")

# 查找所有player-name
print("=" * 50)
print("查找player-name:")
print("=" * 50)
name_pattern = r'class="player-name"[^>]*>([^<]+)<'
names = re.findall(name_pattern, content)
for name in names:
    print(f"  {name}")

# 查找所有player-role
print("\n" + "=" * 50)
print("查找player-role:")
print("=" * 50)
role_pattern = r'class="player-role"[^>]*>([^<]+)<'
roles = re.findall(role_pattern, content)
for role in roles:
    print(f"  {role}")

# 查找role-icons (角色图标URL可能包含角色名)
print("\n" + "=" * 50)
print("查找role-icons:")
print("=" * 50)
icon_pattern = r'role-icons/([^/]+)-\d+x\d+\.png'
icons = re.findall(icon_pattern, content)
unique_icons = sorted(set(icons))
for icon in unique_icons:
    print(f"  {icon}")

# 查找后端JSON中的role数字
print("\n" + "=" * 50)
print("查找后端JSON中的role ID:")
print("=" * 50)
role_id_pattern = r'"role"\s*:\s*(\d+)'
role_ids = re.findall(role_id_pattern, content)
unique_ids = sorted(set(int(x) for x in role_ids))
print(f"找到的role ID: {unique_ids}")

# 查找nickname和role的关联
print("\n" + "=" * 50)
print("尝试找到nickname和role的JSON数据:")
print("=" * 50)
# 查找类似 {"nickname": "xxx", "role": 33} 的模式
player_pattern = r'"nickname"\s*:\s*"([^"]+)"[^}]*"role"\s*:\s*(\d+)|"role"\s*:\s*(\d+)[^}]*"nickname"\s*:\s*"([^"]+)"'
matches = re.findall(player_pattern, content)
for m in matches:
    if m[0] and m[1]:
        print(f"  {m[0]}: role={m[1]}")
    elif m[2] and m[3]:
        print(f"  {m[3]}: role={m[2]}")
