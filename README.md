# CRYPTO BOT 500 — simulador

Protótipo experimental de paper trading para BTCUSDT e ETHUSDT.

## Arquivos
- `app.py`: painel e regras de simulação
- `requirements.txt`: dependências
- `README.md`: instruções

## Publicar no Streamlit
1. Envie os três arquivos para a raiz de um repositório GitHub.
2. No Streamlit Community Cloud, selecione esse repositório.
3. Defina `app.py` como arquivo principal e publique.

## Executar localmente
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Limitações
- Apenas simulação; não envia ordens reais.
- Capital em reais é convertido para USDT usando uma cotação estimada editável.
- Consulta candles públicos da Binance.
- Atualiza quando a página é carregada/recarregada; não é um serviço 24/7.
- Não é estratégia validada nem promessa de lucro.
- Antes de qualquer negociação real, exige backtest, paper trading prolongado, revisão do código e integração separada com API sem permissão de saque.
