import json
cfg = json.load(open('config.json', encoding='utf-8'))
from db_writer import get_connection
c = get_connection(cfg['mssql'])
print('DB OK')
