from database import db
from datetime import datetime
from zoneinfo import ZoneInfo

# Fuso horário Brasil
FUSO_BR = ZoneInfo("America/Sao_Paulo")

def agora_br():
    return datetime.now(FUSO_BR)


# =========================
# USUÁRIO
# =========================
class Usuario(db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)

    # caixa / estoque / admin
    cargo = db.Column(db.String(20), nullable=False, default="caixa")

    criado_em = db.Column(db.DateTime, default=agora_br)

    movimentacoes = db.relationship("Movimentacao", backref="usuario", lazy=True)
    vendas = db.relationship("Venda", backref="operador", lazy=True)


# =========================
# PRODUTO
# =========================
class Produto(db.Model):
    __tablename__ = "produto"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(60), unique=True, nullable=True)
    ean = db.Column(db.String(20), unique=True, nullable=True)
    categoria = db.Column(db.String(80), nullable=True)
    unidade = db.Column(db.String(10), nullable=False, default="un")
    preco = db.Column(db.Float, nullable=False, default=0.0)
    quantidade = db.Column(db.Integer, nullable=False, default=0)
    minimo = db.Column(db.Integer, nullable=False, default=5)
    criado_em = db.Column(db.DateTime, default=agora_br)

    movimentacoes = db.relationship("Movimentacao", backref="produto", lazy=True)
    itens_venda = db.relationship("VendaItem", backref="produto", lazy=True)


# =========================
# MOVIMENTAÇÃO
# =========================
class Movimentacao(db.Model):
    __tablename__ = "movimentacao"

    id = db.Column(db.Integer, primary_key=True)

    produto_id = db.Column(db.Integer, db.ForeignKey("produto.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)

    # ENTRADA / SAIDA / EDIT / EXCLUIR / ADD
    tipo = db.Column(db.String(20), nullable=False)

    quantidade = db.Column(db.Integer, nullable=False, default=0)

    # venda / reposicao / perda / avaria / ajuste...
    motivo = db.Column(db.String(50), nullable=True)

    antes = db.Column(db.Integer, nullable=True)
    depois = db.Column(db.Integer, nullable=True)

    obs = db.Column(db.String(200), nullable=True)

    criado_em = db.Column(db.DateTime, default=agora_br)


# =========================
# VENDA
# =========================
class Venda(db.Model):
    __tablename__ = "venda"

    id = db.Column(db.Integer, primary_key=True)

    # número visual da venda para cupom e tela
    numero_venda = db.Column(db.String(30), unique=True, nullable=True)

    # txid do pix ou identificador interno
    txid = db.Column(db.String(100), unique=True, nullable=True)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)

    forma_pagamento = db.Column(db.String(20), nullable=False)  
    # PIX / DINHEIRO / CARTAO

    status = db.Column(db.String(20), nullable=False, default="PENDENTE")
    # PENDENTE / PAGO / CANCELADO

    total = db.Column(db.Float, nullable=False, default=0.0)
    valor_recebido = db.Column(db.Float, nullable=True)
    troco = db.Column(db.Float, nullable=False, default=0.0)

    observacao = db.Column(db.String(200), nullable=True)

    criado_em = db.Column(db.DateTime, default=agora_br)
    pago_em = db.Column(db.DateTime, nullable=True)
    cancelado_em = db.Column(db.DateTime, nullable=True)

    itens = db.relationship(
        "VendaItem",
        backref="venda",
        lazy=True,
        cascade="all, delete-orphan"
    )


# =========================
# ITENS DA VENDA
# =========================
class VendaItem(db.Model):
    __tablename__ = "venda_item"

    id = db.Column(db.Integer, primary_key=True)

    venda_id = db.Column(db.Integer, db.ForeignKey("venda.id"), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey("produto.id"), nullable=False)

    quantidade = db.Column(db.Integer, nullable=False, default=1)
    preco_unit = db.Column(db.Float, nullable=False, default=0.0)
    subtotal = db.Column(db.Float, nullable=False, default=0.0)