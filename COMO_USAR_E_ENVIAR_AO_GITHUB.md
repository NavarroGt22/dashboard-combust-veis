# Salvar em uma pasta e enviar ao GitHub

## Pasta no computador

1. Baixe `dashboard_combustiveis.zip`.
2. Clique com o botão direito no ZIP e escolha **Extrair Tudo**.
3. Escolha uma pasta, por exemplo `Documentos\AnaliseCombustiveis`.
4. Dentro dela, abra a pasta `dashboard_combustiveis`. O arquivo `app.py` deve estar no mesmo nível de `requirements.txt`.
5. Abra um terminal nessa pasta e siga a instalação do `README.md`.

## GitHub

A aplicação já inclui os dados tratados, por isso funciona ao clonar o repositório e instalar as dependências. O `.gitignore` exclui os CSVs brutos para manter o repositório mais leve. Os arquivos originais continuam no ZIP completo e na pasta local. Para refazer o ETL em outro computador, copie os sete CSVs de volta para `data/raw`.

1. Instale o [Git](https://git-scm.com/downloads) se ainda não estiver disponível.
2. No [GitHub](https://github.com/new), crie um repositório chamado `dashboard-combustiveis`. Deixe sem README, licença ou `.gitignore`, pois o projeto já tem seus arquivos locais.
3. Abra o terminal na pasta que contém `app.py`.
4. Execute os comandos abaixo, substituindo `SEU_USUARIO` pelo nome da sua conta:

```powershell
git init -b main
git add .
git commit -m "Adiciona dashboard de combustíveis e análise de 2018 e 2022"
git remote add origin https://github.com/SEU_USUARIO/dashboard-combustiveis.git
git push -u origin main
```

Na primeira utilização, o Git pode solicitar nome e e-mail para identificar o commit. Configure os seus dados e repita o commit:

```powershell
git config user.name "Seu nome"
git config user.email "seu-email@example.com"
```

O envio pode abrir uma autenticação do GitHub no navegador. Após concluir, atualize a página do repositório para visualizar os arquivos. O endereço do repositório será `https://github.com/SEU_USUARIO/dashboard-combustiveis`.

Para enviar mudanças futuras, dentro da mesma pasta:

```powershell
git add .
git commit -m "Atualiza análise de combustíveis"
git push
```

O `.gitignore` funciona nos comandos Git. Ele não remove arquivos que você arrastar manualmente para o site do GitHub. Se escolher o envio pelo navegador, envie o código, `assets`, `static`, `.streamlit`, `fuel_dashboard`, `scripts`, `tests`, `data/processed` e `outputs`, sem arrastar os CSVs de `data/raw`.

Publicar o código no GitHub guarda e compartilha o projeto. Para disponibilizar o dashboard em um endereço público, ainda é necessário conectar esse repositório a uma hospedagem compatível com Streamlit.

Referência: [guia oficial do GitHub para adicionar um projeto local](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).
