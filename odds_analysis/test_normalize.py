from normalizer import NameNormalizer
import json

n = NameNormalizer()

with open('../database_improved/ligas_times.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('Times LCKC:', data.get('LCKC', [])[:5])
print('Normalized KT Rolster:', n._normalize_string('KT Rolster'))
print('Normalized KT Rolster Challengers:', n._normalize_string('KT Rolster Challengers'))
norm1 = n._normalize_string('KT Rolster')
norm2 = n._normalize_string('KT Rolster Challengers')
print('KT Rolster in KT Rolster Challengers:', norm1 in norm2)
print('Starts with:', norm2.startswith(norm1))

# Teste direto
result = n.normalize_team_name('KT Rolster', 'LCKC')
print('Result:', result)
