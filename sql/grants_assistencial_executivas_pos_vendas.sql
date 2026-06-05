-- Permissões para o dashboard (usuário reconecta_readonly) ler o cadastro
-- oficial de pós-venda usado na aba Clientes Cancelados com Pós Vendas.
-- Executar no Railway como role com privilégio de GRANT (ex.: postgres).

GRANT USAGE ON SCHEMA assistencial TO reconecta_readonly;
GRANT SELECT ON assistencial.executivas_pos_vendas TO reconecta_readonly;
