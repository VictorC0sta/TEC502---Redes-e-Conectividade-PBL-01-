# testes.py — Testes de integração do sistema
import requests
import socket
import json

SERVER = "http://172.16.103.5:5050"

def teste_server_online():
    r = requests.get(f"{SERVER}/estado", timeout=3)
    assert r.status_code == 200
    print("✅ Server online e respondendo")

def teste_historico():
    r = requests.get(f"{SERVER}/historico", timeout=3)
    dados = r.json()
    assert isinstance(dados, list)
    print(f"✅ Histórico retorna lista com {len(dados)} registros")

def teste_atuadores():
    r = requests.get(f"{SERVER}/atuadores", timeout=3)
    dados = r.json()
    assert isinstance(dados, list)
    print(f"✅ Atuadores retorna lista com {len(dados)} registros")

def teste_alarme_manual():
    r = requests.post(f"{SERVER}/ativar/alarme", timeout=3)
    assert r.json()["status"] == "ok"
    print("✅ Alarme manual acionado com sucesso")

def teste_resfriamento_manual():
    r = requests.post(f"{SERVER}/ativar/resfriamento", timeout=3)
    assert r.json()["status"] == "ok"
    print("✅ Resfriamento manual acionado com sucesso")

def teste_sensor_via_http():
    payload = {"id": "sensor_teste", "tipo": "temperatura", "valor": 40.0}
    r = requests.post(f"{SERVER}/sensor", json=payload, timeout=3)
    assert r.json()["status"] == "ok"
    print("✅ Ingestão de sensor via HTTP funcionando")

def teste_rota_invalida():
    r = requests.get(f"{SERVER}/rota_inexistente", timeout=3)
    assert r.status_code == 404
    print("✅ Rota inválida retorna 404 corretamente")

def teste_json_invalido():
    r = requests.post(f"{SERVER}/sensor",
                      data="isso nao e json",
                      headers={"Content-Type": "application/json"},
                      timeout=3)
    assert r.status_code == 400
    print("✅ JSON inválido retorna 400 corretamente")

if __name__ == "__main__":
    testes = [
        teste_server_online,
        teste_historico,
        teste_atuadores,
        teste_alarme_manual,
        teste_resfriamento_manual,
        teste_sensor_via_http,
        teste_rota_invalida,
        teste_json_invalido,
    ]
    for t in testes:
        try:
            t()
        except Exception as e:
            print(f"❌ {t.__name__} falhou: {e}")