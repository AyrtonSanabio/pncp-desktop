# Compartilhamento somente leitura por túnel

O aplicativo é desktop e o banco SQLite é um arquivo local. Nunca compartilhe o arquivo
`pncp.sqlite3`, uma pasta do disco ou uma porta SQLite pela internet. Para uma consulta
temporária por outra pessoa, use o visualizador local somente leitura e publique apenas a
porta dele por um túnel HTTP.

## Limites do visualizador

- escuta exclusivamente em `127.0.0.1` (não fica visível na rede local);
- abre o banco com `mode=ro` e `PRAGMA query_only=ON`;
- disponibiliza busca e detalhe de contratações e itens já sincronizados;
- não oferece sincronização, exportação, backup, alteração, execução de SQL ou download de
  documentos;
- exige autenticação HTTP Basic antes de revelar qualquer resposta e não grava termos de
  busca ou cabeçalhos de autenticação no terminal.

O túnel deve apontar para o visualizador, nunca para o banco.

## Iniciar no Windows

Abra um `cmd.exe` e defina uma senha longa que será válida apenas naquela janela:

```bat
set /p PNCP_READONLY_PASSWORD=Informe uma senha com pelo menos 16 caracteres: 
```

Em seguida, inicie o visualizador. Ajuste o caminho do banco se ele estiver em outro local:

```bat
"C:\caminho\para\ConsultaPNCP.exe" --share-readonly --share-database "A:\Projetos\pncp-dados\pncp.sqlite3"
```

Ele confirma `Visualizador somente leitura em http://127.0.0.1:8765`. Mantenha essa janela
aberta. Em outra janela `cmd.exe`, inicie o ngrok:

```bat
"A:\ngrok-v3-stable-windows-amd64\ngrok.exe" http 8765
```

Envie à pessoa somente a URL `https://...ngrok-free.app` exibida pelo ngrok e, por um canal
separado, o usuário `consulta` e a senha escolhida. Encerre ambas as janelas quando o acesso
não for mais necessário.

## Regras de segurança

- use senha exclusiva, aleatória e com no mínimo 16 caracteres;
- não envie o authtoken do ngrok; ele dá controle sobre sua conta ngrok;
- a autenticação Basic do visualizador protege a página, mas quem receber a senha também
  conseguirá entrar enquanto o túnel estiver ativo;
- para uma restrição por identidade de e-mail em vez de senha compartilhada, configure OAuth
  ou uma política de acesso no ngrok antes de enviar a URL;
- o conteúdo vem de uma cópia local de dados públicos do PNCP e não substitui o portal oficial.
