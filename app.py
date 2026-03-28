from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import db
from models import Usuario, Produto, Movimentacao, Venda, VendaItem
from flask_migrate import Migrate
from sqlalchemy import func
from functools import wraps
from datetime import datetime, date
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash, check_password_hash
import os
import time
import uuid
import mercadopago

# ✅ FUSO BRASIL
FUSO_BR = ZoneInfo("America/Sao_Paulo")

def agora_br():
    return datetime.now(FUSO_BR)

# ⚠️ USE TOKEN DE TESTE!!!
MP_ACCESS_TOKEN = "APP_USR-1919354004447670-032714-e0db1140c259a95b32d2aa1c5473630a-1323236580"

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

app = Flask(__name__)

# =========================
# CONFIG
# =========================
os.makedirs(app.instance_path, exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "estoque.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "segredo_supermercado"

# código para permitir cadastro de usuário de estoque
app.config["ADMIN_CADASTRO_CODE"] = "ADMIN123"

db.init_app(app)
migrate = Migrate(app, db)

with app.app_context():
    db.create_all()


# =========================
# DECORATORS
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Faça login para continuar.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cargo = session.get("cargo")

            if not cargo:
                flash("Faça login novamente.", "warning")
                return redirect(url_for("login"))

            if cargo not in roles:
                flash("Acesso negado. Você não tem permissão.", "danger")
                return redirect(url_for("acesso_negado"))

            return f(*args, **kwargs)
        return wrapper
    return decorator


# =========================
# HELPERS
# =========================
def gerar_sku(nome: str) -> str:
    base = "".join([c for c in (nome or "").upper() if c.isalnum()])
    base = base[:3] if len(base) >= 3 else base

    ultimo = Produto.query.order_by(Produto.id.desc()).first()
    proximo_id = (ultimo.id + 1) if ultimo else 1

    return f"{base}{proximo_id:04d}"


def registrar_mov(produto_id, tipo, quantidade, motivo, antes, depois, obs=None):
    mov = Movimentacao(
        produto_id=produto_id,
        usuario_id=session.get("usuario_id"),
        tipo=(tipo or "").upper().strip(),
        quantidade=int(quantidade) if str(quantidade).lstrip("-").isdigit() else 0,
        motivo=(motivo or "ajuste").strip().lower(),
        antes=antes,
        depois=depois,
        obs=obs
    )
    db.session.add(mov)


def senha_ok(user: Usuario, senha_digitada: str) -> bool:
    if not user or not senha_digitada:
        return False

    senha_db = (user.senha or "").strip()

    if senha_db.startswith("pbkdf2:") or senha_db.startswith("scrypt:"):
        return check_password_hash(senha_db, senha_digitada)

    if senha_db == senha_digitada:
        user.senha = generate_password_hash(senha_digitada)
        db.session.commit()
        return True

    return False


def parse_int(valor, default=0):
    try:
        return int(str(valor).strip())
    except Exception:
        return default


def parse_float(valor, default=0.0):
    try:
        return float(str(valor).replace(",", ".").strip())
    except Exception:
        return default


# =========================
# LOGIN / REGISTER / LOGOUT
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "").strip()

        user = Usuario.query.filter_by(usuario=usuario).first()
        if user and senha_ok(user, senha):
            session["usuario_id"] = user.id
            session["usuario"] = user.usuario
            session["cargo"] = getattr(user, "cargo", "caixa")

            flash("Login realizado com sucesso!", "success")

            if session["cargo"] == "estoque":
                return redirect(url_for("dashboard"))
            return redirect(url_for("venda_rapida"))

        return render_template("login.html", erro="Usuário ou senha inválidos.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "").strip()
        cargo = (request.form.get("cargo") or "caixa").strip().lower()
        admin_code = (request.form.get("admin_code") or "").strip()

        if not usuario or not senha:
            return render_template("register.html", erro="Preencha usuário e senha.")

        if cargo not in ["caixa", "estoque"]:
            cargo = "caixa"

        if cargo == "estoque" and admin_code != app.config["ADMIN_CADASTRO_CODE"]:
            return render_template("register.html", erro="Código admin inválido para criar usuário do estoque.")

        existe = Usuario.query.filter_by(usuario=usuario).first()
        if existe:
            return render_template("register.html", erro="Esse usuário já existe.")

        senha_hash = generate_password_hash(senha)
        novo = Usuario(usuario=usuario, senha=senha_hash, cargo=cargo)

        db.session.add(novo)
        db.session.commit()

        flash("Usuário cadastrado com sucesso! Faça login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))


# =========================
# ACESSO NEGADO
# =========================
@app.route("/acesso_negado")
@login_required
def acesso_negado():
    return render_template("acesso_negado.html")


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
@role_required("estoque")
def dashboard():
    produtos = Produto.query.order_by(Produto.nome.asc()).all()

    total_produtos = Produto.query.count()

    total_itens = (
        db.session.query(func.coalesce(func.sum(Produto.quantidade), 0))
        .scalar() or 0
    )

    estoque_baixo = (
        Produto.query
        .filter(Produto.quantidade > 0, Produto.quantidade <= Produto.minimo)
        .count()
    )

    produtos_zerados = (
        Produto.query
        .filter(Produto.quantidade == 0)
        .count()
    )

    hoje_inicio = datetime.combine(date.today(), datetime.min.time())

    ultima_mov_hoje = (
        Movimentacao.query
        .filter(Movimentacao.criado_em >= hoje_inicio)
        .order_by(Movimentacao.criado_em.desc())
        .first()
    )

    total_vendido_hoje = (
        db.session.query(func.coalesce(func.sum(Movimentacao.quantidade), 0))
        .filter(
            Movimentacao.tipo == "SAIDA",
            Movimentacao.criado_em >= hoje_inicio
        )
        .scalar() or 0
    )

    return render_template(
        "dashboard.html",
        produtos=produtos,
        total_produtos=total_produtos,
        total_itens=total_itens,
        estoque_baixo=estoque_baixo,
        produtos_zerados=produtos_zerados,
        ultima_mov_hoje=ultima_mov_hoje,
        total_vendido_hoje=total_vendido_hoje
    )

# =========================
# DETALHE DO PRODUTO
# =========================
@app.route("/produto/<int:id>")
@login_required
@role_required("estoque")
def produto_detalhe(id):
    produto = Produto.query.get_or_404(id)

    historico = (
        db.session.query(
            Movimentacao.criado_em,
            Movimentacao.tipo,
            Movimentacao.quantidade,
            Movimentacao.motivo,
            Movimentacao.antes,
            Movimentacao.depois,
            Movimentacao.obs
        )
        .filter(Movimentacao.produto_id == produto.id)
        .order_by(Movimentacao.criado_em.desc())
        .limit(100)
        .all()
    )

    historico_fmt = [{
        "data": h.criado_em.strftime("%d/%m/%Y %H:%M") if h.criado_em else "-",
        "tipo": h.tipo or "-",
        "quantidade": h.quantidade or 0,
        "motivo": h.motivo or "-",
        "antes": h.antes,
        "depois": h.depois,
        "obs": h.obs or ""
    } for h in historico]

    return render_template("produto_detalhe.html", produto=produto, historico=historico_fmt)


# =========================
# MOVIMENTAR PRODUTO
# =========================
@app.route("/movimentar/<int:id>", methods=["POST"])
@login_required
@role_required("estoque")
def movimentar(id):
    produto = Produto.query.get_or_404(id)

    tipo = request.form.get("tipo", "").upper().strip()
    motivo = request.form.get("motivo", "ajuste").strip().lower()
    obs = request.form.get("obs", "").strip()
    qtd = parse_int(request.form.get("quantidade", "0"), 0)

    if qtd <= 0:
        flash("Quantidade inválida.", "warning")
        return redirect(url_for("dashboard"))

    antes = int(produto.quantidade or 0)

    if tipo == "ENTRADA":
        produto.quantidade = antes + qtd
        depois = produto.quantidade
        registrar_mov(produto.id, "ENTRADA", qtd, motivo, antes, depois, obs=obs or "Entrada")

    elif tipo == "SAIDA":
        if qtd > antes:
            flash("Estoque insuficiente para saída.", "danger")
            return redirect(url_for("dashboard"))

        produto.quantidade = antes - qtd
        depois = produto.quantidade
        registrar_mov(produto.id, "SAIDA", qtd, motivo, antes, depois, obs=obs or "Saída")

    else:
        flash("Tipo de movimentação inválido.", "danger")
        return redirect(url_for("dashboard"))

    db.session.commit()
    flash("Movimentação realizada com sucesso!", "success")
    return redirect(url_for("dashboard"))


# =========================
# CADASTRAR PRODUTO
# =========================
@app.route("/estoque", methods=["GET", "POST"])
@login_required
@role_required("estoque")
def estoque():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        quantidade_int = parse_int(request.form.get("quantidade", "0"), 0)
        minimo_int = parse_int(request.form.get("minimo", "5"), 5)
        preco_float = parse_float(request.form.get("preco", "0"), 0.0)
        sku = request.form.get("sku", "").strip()
        ean = request.form.get("ean", "").strip()
        categoria = request.form.get("categoria", "").strip()
        unidade = request.form.get("unidade", "un").strip()

        if not nome:
            return render_template("estoque.html", erro="Digite o nome do produto.")

        if not sku:
            sku = gerar_sku(nome)

        if sku and Produto.query.filter_by(sku=sku).first():
            return render_template("estoque.html", erro="Já existe um produto com esse SKU.")

        if ean and Produto.query.filter_by(ean=ean).first():
            return render_template("estoque.html", erro="Já existe um produto com esse EAN.")

        novo = Produto(
            nome=nome,
            quantidade=quantidade_int,
            minimo=minimo_int,
            preco=preco_float,
            sku=sku,
            ean=ean or None,
            categoria=categoria or None,
            unidade=unidade or "un"
        )

        db.session.add(novo)
        db.session.commit()

        registrar_mov(
            novo.id,
            "ADD",
            quantidade_int,
            "cadastro",
            0,
            quantidade_int,
            obs="Cadastro do produto"
        )
        db.session.commit()

        flash("Produto cadastrado com sucesso!", "success")
        return redirect(url_for("dashboard"))

    return render_template("estoque.html")


# =========================
# EDITAR PRODUTO
# =========================
@app.route("/editar_produto/<int:id>", methods=["POST"])
@login_required
@role_required("estoque")
def editar_produto(id):
    produto = Produto.query.get_or_404(id)
    antes = int(produto.quantidade or 0)

    nome = request.form.get("nome", "").strip()
    quantidade = request.form.get("quantidade", "").strip()
    minimo = request.form.get("minimo", "").strip()
    preco = request.form.get("preco", "").strip()
    categoria = request.form.get("categoria", "").strip()
    unidade = request.form.get("unidade", "").strip()
    sku = request.form.get("sku", "").strip()
    ean = request.form.get("ean", "").strip()

    alterou = []

    if nome and nome != produto.nome:
        produto.nome = nome
        alterou.append("nome")

    if quantidade:
        qtd = parse_int(quantidade, produto.quantidade)
        if qtd != produto.quantidade:
            produto.quantidade = qtd
            alterou.append("quantidade")

    if minimo:
        mn = parse_int(minimo, produto.minimo)
        if mn != produto.minimo:
            produto.minimo = mn
            alterou.append("minimo")

    if preco:
        preco_float = parse_float(preco, produto.preco)
        if float(preco_float) != float(produto.preco or 0):
            produto.preco = preco_float
            alterou.append("preco")

    if categoria != (produto.categoria or ""):
        produto.categoria = categoria or None
        alterou.append("categoria")

    if unidade and unidade != (produto.unidade or "un"):
        produto.unidade = unidade
        alterou.append("unidade")

    if sku != (produto.sku or ""):
        if sku:
            existe = Produto.query.filter(Produto.sku == sku, Produto.id != produto.id).first()
            if existe:
                flash("SKU já existe em outro produto.", "danger")
                return redirect(url_for("dashboard"))
            produto.sku = sku
        else:
            produto.sku = None
        alterou.append("sku")

    if ean != (produto.ean or ""):
        if ean:
            existe = Produto.query.filter(Produto.ean == ean, Produto.id != produto.id).first()
            if existe:
                flash("EAN já existe em outro produto.", "danger")
                return redirect(url_for("dashboard"))
            produto.ean = ean
        else:
            produto.ean = None
        alterou.append("ean")

    depois = int(produto.quantidade or 0)

    if alterou:
        registrar_mov(
            produto.id,
            "EDIT",
            abs(depois - antes),
            "edicao",
            antes,
            depois,
            obs="Editou: " + ", ".join(alterou)
        )

    db.session.commit()
    flash("Produto atualizado com sucesso!", "success")
    return redirect(url_for("dashboard"))


# =========================
# EXCLUIR PRODUTO
# =========================
@app.route("/excluir_produto/<int:id>")
@login_required
@role_required("estoque")
def excluir_produto(id):
    produto = Produto.query.get_or_404(id)
    nome_produto = produto.nome

    try:
        movs = Movimentacao.query.filter_by(produto_id=produto.id).all()
        for mov in movs:
            db.session.delete(mov)

        db.session.delete(produto)
        db.session.commit()

        flash(f"Produto '{nome_produto}' excluído com sucesso.", "success")
    except Exception:
        db.session.rollback()
        flash("Não foi possível excluir o produto.", "danger")

    return redirect(url_for("dashboard"))


# =========================
# RELATÓRIOS
# =========================
@app.route("/relatorios")
@login_required
@role_required("estoque")
def relatorios():
    total_produtos = int(Produto.query.count() or 0)

    estoque_baixo = int(
        Produto.query
        .filter(Produto.quantidade > 0)
        .filter(Produto.quantidade <= Produto.minimo)
        .count() or 0
    )

    estoque_zerado = int(
        Produto.query
        .filter(Produto.quantidade == 0)
        .count() or 0
    )

    estoque_normal = int(max(0, total_produtos - estoque_baixo - estoque_zerado))

    ultimos_db = (
        db.session.query(
            Movimentacao.criado_em,
            Movimentacao.tipo,
            Movimentacao.quantidade,
            Movimentacao.motivo,
            Produto.nome.label("produto_nome")
        )
        .join(Produto, Produto.id == Movimentacao.produto_id)
        .order_by(Movimentacao.criado_em.desc())
        .limit(15)
        .all()
    )

    ultimos = [{
        "data": u.criado_em.strftime("%d/%m/%Y %H:%M") if u.criado_em else "-",
        "produto": u.produto_nome or "-",
        "tipo": u.tipo or "-",
        "quantidade": int(u.quantidade or 0),
        "motivo": u.motivo or "-"
    } for u in ultimos_db]

    top = (
        db.session.query(
            Produto.nome.label("nome"),
            func.coalesce(func.sum(Movimentacao.quantidade), 0).label("qtd")
        )
        .join(Movimentacao, Movimentacao.produto_id == Produto.id)
        .filter(Movimentacao.tipo == "SAIDA")
        .group_by(Produto.nome)
        .order_by(func.coalesce(func.sum(Movimentacao.quantidade), 0).desc())
        .limit(5)
        .all()
    )

    top_labels = [(t.nome or "") for t in top]
    top_values = [int(t.qtd or 0) for t in top]

    return render_template(
        "relatorios.html",
        total_produtos=total_produtos,
        estoque_normal=estoque_normal,
        estoque_baixo=estoque_baixo,
        estoque_zerado=estoque_zerado,
        ultimos=ultimos,
        top_labels=top_labels,
        top_values=top_values
    )


# =========================
# PDV / VENDA RÁPIDA
# =========================
@app.route("/venda_rapida", methods=["GET"])
@login_required
@role_required("caixa", "estoque")
def venda_rapida():
    return render_template("pdv.html")


@app.route("/api/produtos")
@login_required
@role_required("caixa", "estoque")
def api_produtos():
    termo = (request.args.get("q") or "").strip()

    query = Produto.query
    if termo:
        query = query.filter(Produto.nome.ilike(f"%{termo}%"))

    produtos = query.order_by(Produto.nome.asc()).limit(30).all()

    return jsonify({
        "ok": True,
        "produtos": [
            {
                "id": p.id,
                "nome": p.nome,
                "ean": p.ean,
                "preco": float(p.preco or 0),
                "estoque": int(p.quantidade or 0),
                "unidade": p.unidade or "un"
            }
            for p in produtos
        ]
    })


@app.route("/api/produto_por_ean")
@login_required
@role_required("caixa", "estoque")
def api_produto_por_ean():
    ean = (request.args.get("ean") or "").strip()
    if not ean:
        return jsonify({"ok": False, "msg": "EAN vazio"}), 400

    p = Produto.query.filter_by(ean=ean).first()
    if not p:
        return jsonify({"ok": False, "msg": "Produto não encontrado"}), 404

    return jsonify({
        "ok": True,
        "produto": {
            "id": p.id,
            "nome": p.nome,
            "ean": p.ean,
            "preco": float(p.preco or 0.0),
            "estoque": int(p.quantidade or 0),
            "unidade": p.unidade or "un"
        }
    })


@app.route("/api/finalizar_venda", methods=["POST"])
@login_required
@role_required("caixa", "estoque")
def api_finalizar_venda():
    data = request.get_json() or {}
    forma = (data.get("forma_pagamento") or "").strip().lower()
    valor_recebido = data.get("valor_recebido")
    carrinho = data.get("carrinho") or []

    if forma not in ["cartao", "dinheiro"]:
        return jsonify({"ok": False, "msg": "Forma inválida"}), 400

    if not carrinho:
        return jsonify({"ok": False, "msg": "Carrinho vazio"}), 400

    total = 0.0
    itens_db = []

    for item in carrinho:
        try:
            produto_id = int(item["produto_id"])
            qtd = int(item["qtd"])
            preco = float(item.get("preco", 0))
        except Exception:
            return jsonify({"ok": False, "msg": "Carrinho inválido"}), 400

        if qtd <= 0:
            continue

        produto = Produto.query.get(produto_id)
        if not produto:
            return jsonify({"ok": False, "msg": "Produto não encontrado"}), 404

        antes = int(produto.quantidade or 0)
        if antes < qtd:
            return jsonify({"ok": False, "msg": f"Estoque insuficiente: {produto.nome}"}), 400

        subtotal = preco * qtd
        total += subtotal
        itens_db.append((produto, qtd, preco, subtotal, antes))

    if not itens_db:
        return jsonify({"ok": False, "msg": "Carrinho vazio"}), 400

    troco = None
    valor_recebido_float = None

    if forma == "dinheiro":
        valor_recebido_float = parse_float(valor_recebido, 0.0)
        if valor_recebido_float < total:
            return jsonify({"ok": False, "msg": "Valor recebido insuficiente"}), 400
        troco = valor_recebido_float - total

    for produto, qtd, preco, subtotal, antes in itens_db:
        produto.quantidade = antes - qtd
        registrar_mov(
            produto.id,
            "SAIDA",
            qtd,
            "venda",
            antes,
            produto.quantidade,
            obs="Venda PDV (EAN)"
        )

    db.session.commit()

    session["ultimo_cupom"] = {
        "venda_id": int(datetime.now().timestamp()),
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "operador": session.get("usuario", "caixa"),
        "forma": forma,
        "valor_recebido": valor_recebido_float if forma == "dinheiro" else None,
        "troco": troco,
        "total": total,
        "itens": [
            {
                "nome": p.nome,
                "ean": p.ean,
                "qtd": qtd,
                "preco_unit": preco,
                "subtotal": subtotal
            }
            for (p, qtd, preco, subtotal, antes) in itens_db
        ]
    }

    return jsonify({
        "ok": True,
        "total": total,
        "troco": troco,
        "redirect": url_for("cupom")
    })

@app.route("/api/criar_pix", methods=["POST"])
@login_required
@role_required("caixa", "estoque")
def api_criar_pix():
    data = request.get_json() or {}
    carrinho = data.get("carrinho") or []

    if not carrinho:
        return jsonify({"ok": False, "msg": "Carrinho vazio"}), 400

    total = 0.0
    itens_processados = []

    for item in carrinho:
        try:
            produto_id = int(item["produto_id"])
            qtd = int(item["qtd"])
            preco = float(item.get("preco", 0))
        except Exception:
            return jsonify({"ok": False, "msg": "Carrinho inválido"}), 400

        if qtd <= 0:
            continue

        produto = Produto.query.get(produto_id)
        if not produto:
            return jsonify({"ok": False, "msg": "Produto não encontrado"}), 404

        if int(produto.quantidade or 0) < qtd:
            return jsonify({"ok": False, "msg": f"Estoque insuficiente: {produto.nome}"}), 400

        subtotal = preco * qtd
        total += subtotal

        itens_processados.append({
            "produto": produto,
            "qtd": qtd,
            "preco": preco,
            "subtotal": subtotal
        })

    if not itens_processados:
        return jsonify({"ok": False, "msg": "Carrinho vazio"}), 400

    txid_local = str(uuid.uuid4())

    venda = Venda(
        txid=txid_local,
        forma_pagamento="pix",
        status="PENDENTE",
        total=total
    )
    db.session.add(venda)
    db.session.flush()

    for item in itens_processados:
        db.session.add(VendaItem(
            venda_id=venda.id,
            produto_id=item["produto"].id,
            quantidade=item["qtd"],
            preco_unit=item["preco"]
        ))

    payment_data = {
        "transaction_amount": round(total, 2),
        "description": f"Venda PDV #{venda.id}",
        "payment_method_id": "pix",
        "payer": {
            "email": "cliente@example.com",
            "first_name": "Cliente",
            "last_name": "PDV"
        }
    }

    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {
        "x-idempotency-key": txid_local
    }

    payment_response = sdk.payment().create(payment_data, request_options)
    payment = payment_response.get("response", {})

    if payment_response.get("status") not in [200, 201]:
        db.session.rollback()
        return jsonify({
            "ok": False,
            "msg": payment.get("message", "Erro ao gerar PIX real")
        }), 400

    venda.txid = str(payment.get("id") or txid_local)
    db.session.commit()

    poi = payment.get("point_of_interaction", {}) or {}
    tx_data = poi.get("transaction_data", {}) or {}

    return jsonify({
        "ok": True,
        "txid": venda.txid,
        "total": total,
        "status_mp": payment.get("status"),
        "pix_copia_cola": tx_data.get("qr_code"),
        "qr_code_base64": tx_data.get("qr_code_base64")
    })


@app.route("/api/status_pix/<txid>")
@login_required
@role_required("caixa", "estoque")
def status_pix(txid):
    venda = Venda.query.filter_by(txid=txid).first()

    if not venda:
        return jsonify({"ok": False, "msg": "PIX não encontrado"}), 404

    return jsonify({
        "ok": True,
        "status": venda.status
    })


@app.route("/api/confirmar_pix/<txid>", methods=["POST"])
@login_required
@role_required("caixa", "estoque")
def confirmar_pix(txid):
    venda = Venda.query.filter_by(txid=txid).first()

    if not venda:
        return jsonify({"ok": False, "msg": "Venda PIX não encontrada"}), 404

    if venda.status == "PAGO":
        return jsonify({
            "ok": True,
            "msg": "PIX já confirmado",
            "redirect": url_for("cupom")
        })

    itens = VendaItem.query.filter_by(venda_id=venda.id).all()
    if not itens:
        return jsonify({"ok": False, "msg": "Nenhum item encontrado para esta venda"}), 400

    itens_cupom = []

    for item in itens:
        produto = Produto.query.get(item.produto_id)
        if not produto:
            return jsonify({"ok": False, "msg": "Produto da venda não encontrado"}), 404

        antes = int(produto.quantidade or 0)
        if antes < item.quantidade:
            return jsonify({"ok": False, "msg": f"Estoque insuficiente: {produto.nome}"}), 400

        produto.quantidade = antes - item.quantidade

        registrar_mov(
            produto.id,
            "SAIDA",
            item.quantidade,
            "venda",
            antes,
            produto.quantidade,
            obs="Venda PDV (PIX)"
        )

        subtotal = float(item.preco_unit or 0) * int(item.quantidade or 0)

        itens_cupom.append({
            "nome": produto.nome,
            "ean": produto.ean,
            "qtd": item.quantidade,
            "preco_unit": float(item.preco_unit or 0),
            "subtotal": subtotal
        })

    venda.status = "PAGO"
    venda.forma_pagamento = "pix"
    db.session.commit()

    session["ultimo_cupom"] = {
        "venda_id": venda.id,
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "operador": session.get("usuario", "caixa"),
        "forma": "pix",
        "valor_recebido": None,
        "troco": None,
        "total": float(venda.total or 0),
        "itens": itens_cupom
    }

    return jsonify({
        "ok": True,
        "redirect": url_for("cupom")
    })

# =========================
# CUPOM / NOTINHA
# =========================
@app.route("/cupom")
@login_required
@role_required("caixa", "estoque")
def cupom():
    cupom_data = session.get("ultimo_cupom")
    if not cupom_data:
        flash("Nenhum cupom disponível.", "warning")
        return redirect(url_for("venda_rapida"))
    return render_template("cupom.html", cupom=cupom_data)


@app.route("/notinha")
@login_required
@role_required("caixa", "estoque")
def notinha():
    cupom_data = session.get("ultimo_cupom")
    if not cupom_data:
        flash("Nenhuma notinha disponível.", "warning")
        return redirect(url_for("venda_rapida"))
    return render_template("notinha.html", cupom=cupom_data)


# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(debug=True)

