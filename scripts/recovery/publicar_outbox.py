#!/usr/bin/env python3
"""Recupera OUTBOX pendientes SIN DynamoDB Streams (Academy / LabRole).

Por defecto solo lista metadatos. Para publicar requiere --apply --confirm PUBLICAR.
No usa API Gateway, no elimina registros y mantiene el mismo event_id.
"""
import argparse
import json
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

TENANTS = ("CLIMALIMA", "FRIOSUR", "TECNINORTE")
TIPOS = {"partes": "ParteFinalizado", "agenda": "VisitaCompletada"}


def argumentos():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servicio", choices=tuple(TIPOS), required=True)
    parser.add_argument("--tenant", choices=TENANTS, required=True)
    parser.add_argument("--stage", default="dev", choices=("dev", "test", "prod"))
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--max", type=int, default=10, dest="limite")
    parser.add_argument("--event-id", default=None, help="Seleccionar un único evento OUTBOX")
    parser.add_argument("--apply", action="store_true", help="Publicar en SNS")
    parser.add_argument("--confirm", default="", help="Con --apply escribir PUBLICAR")
    return parser.parse_args()


def pendientes(tabla, tenant, limite):
    """Consulta SK OUTBOX#, nunca hace Scan completo de la tabla."""
    token = None
    contados = 0
    while contados < limite:
        parametros = {
            "KeyConditionExpression": (
                Key("PK").eq(f"TENANT#{tenant}") & Key("SK").begins_with("OUTBOX#")
            ),
            "FilterExpression": Attr("estado").eq("PENDIENTE"),
            "ConsistentRead": True,
        }
        if token:
            parametros["ExclusiveStartKey"] = token
        resultado = tabla.query(**parametros)
        for item in resultado.get("Items", []):
            yield item
            contados += 1
            if contados >= limite:
                return
        token = resultado.get("LastEvaluatedKey")
        if not token:
            return


def buscar_evento(tabla, tenant, event_id):
    """Busca un único OUTBOX por su clave primaria; nunca otros eventos."""
    try:
        canonical = str(uuid.UUID(event_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise SystemExit("--event-id debe ser un UUID válido") from exc
    if canonical != event_id:
        raise SystemExit("--event-id debe ser un UUID canónico en minúsculas")
    llave = {"PK": f"TENANT#{tenant}", "SK": f"OUTBOX#{canonical}"}
    return tabla.get_item(Key=llave, ConsistentRead=True).get("Item")


def validar(item, tenant, tipo):
    payload = item.get("payload")
    if (item.get("entity_type") != "OUTBOX"
            or item.get("tenant_id") != tenant
            or item.get("event_type") != tipo
            or item.get("estado") != "PENDIENTE"
            or not isinstance(payload, dict)
            or payload.get("event_id") != item.get("event_id")
            or payload.get("event_type") != tipo
            or payload.get("tenant_id") != tenant):
        raise ValueError("OUTBOX pendiente con datos inconsistentes")
    return payload


def main():
    args = argumentos()
    if not 1 <= args.limite <= 100:
        raise SystemExit("--max debe estar entre 1 y 100")
    if args.apply and (args.confirm != "PUBLICAR" or not args.event_id):
        raise SystemExit("Para publicar un evento exacto: --event-id UUID --apply --confirm PUBLICAR")
    session = boto3.Session(region_name=args.region)
    sts = session.client("sts")
    cuenta = sts.get_caller_identity()["Account"]
    tabla_nombre = f"trazora-{args.servicio}-{args.stage}"
    tema_arn = f"arn:aws:sns:{args.region}:{cuenta}:trazora-fsm-eventos-{args.stage}"
    tabla = session.resource("dynamodb").Table(tabla_nombre)
    sns = session.client("sns")
    tipo = TIPOS[args.servicio]
    total = 0
    if args.event_id:
        encontrado = buscar_evento(tabla, args.tenant, args.event_id)
        if not encontrado:
            raise SystemExit("No se encontró el OUTBOX exacto para ese tenant e ID")
        if encontrado.get("estado") == "PUBLICADO":
            print(json.dumps({"event_id": args.event_id, "estado": "PUBLICADO",
                              "accion": "NINGUNA", "motivo": "Ya publicado"}))
            return
        elegidos = (encontrado,)
    else:
        elegidos = pendientes(tabla, args.tenant, args.limite)
    for item in elegidos:
        payload = validar(item, args.tenant, tipo)
        evento_id = item["event_id"]
        total += 1
        print(json.dumps({
            "modo": "APPLY" if args.apply else "DRY_RUN",
            "tabla": tabla_nombre, "tenant": args.tenant,
            "event_type": tipo, "event_id": evento_id
        }))
        if not args.apply:
            continue
        # SNS puede aceptar y el marcado posterior fallar: se reintentara
        # con el MISMO event_id y los consumidores reconoceran el duplicado.
        sns.publish(
            TopicArn=tema_arn,
            Message=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        try:
            tabla.update_item(
                Key={"PK": item["PK"], "SK": item["SK"]},
                UpdateExpression="SET #estado=:pub, publicado_en=:fecha",
                ConditionExpression="#estado=:pend",
                ExpressionAttributeNames={"#estado": "estado"},
                ExpressionAttributeValues={
                    ":pub": "PUBLICADO", ":pend": "PENDIENTE",
                    ":fecha": datetime.now(timezone.utc).isoformat(),
                },
            )
        except ClientError as exc:
            # No ocultar un error de estado; SNS ya pudo entregar el evento.
            print(json.dumps({"tipo": "ERROR", "operacion": "marcar_outbox",
                              "event_id": evento_id,
                              "error": exc.response.get("Error", {}).get("Code")}))
            raise
    print(json.dumps({"revisados": total, "modo": "APPLY" if args.apply else "DRY_RUN"}))


if __name__ == "__main__":
    main()
