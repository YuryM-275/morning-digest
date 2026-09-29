# Запуск поллинг-моста tg_bridge.py в скрытом окне (задача планировщика ClaudeTGBridge).
# Лог дописывается в data/bridge_log.txt (мост пишет только в stdout).
# Ротация: если лог вырос за 2 МБ — обнуляем при следующем старте.

$log = 'D:\Cabinet\AI\Claude\project_news\data\bridge_log.txt'
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 2MB)) {
    Set-Content -Path $log -Value ''
}

Set-Location 'D:\Cabinet\AI\Claude\project_news'
py -X utf8 tg_bridge.py *>> $log