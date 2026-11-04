from __future__ import annotations

import argparse
from decimal import Decimal
from collections import Counter
import json
import re
from pathlib import Path
import sqlite3
import time
from typing import Iterator
from generar_datos import AUX, SERVICES, TENANTS
from validar_datos import TABLE, rows, validate

ORDER=('usuarios','clientes','tecnicos','jornadas','ordenes','agenda','bloques','controles','partes','marcadores')


def canonical(item: dict) -> str:
    return json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=lambda value: int(value) if isinstance(value,Decimal) and value == value.to_integral_value() else (_ for _ in ()).throw(TypeError(f'Tipo no admitido: {type(value).__name__}')))


def items(folder: Path) -> Iterator[tuple[str,dict]]:
    for service in ORDER:
        for item in rows(folder/f'{service}.jsonl'):
            yield TABLE.get(service,service),item


class LocalStore:
    def __init__(self, path: Path) -> None:
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS items (tabla TEXT NOT NULL, pk TEXT NOT NULL, sk TEXT NOT NULL, cuerpo TEXT NOT NULL, PRIMARY KEY(tabla,pk,sk))')
        self.db.commit()

    def insert(self, table: str, item: dict) -> str:
        encoded=canonical(item)
        with self.db:
            result=self.db.execute('INSERT OR IGNORE INTO items VALUES (?,?,?,?)',(table,item['PK'],item['SK'],encoded))
        if result.rowcount:
            return 'escritos'
        current=self.db.execute('SELECT cuerpo FROM items WHERE tabla=? AND pk=? AND sk=?',(table,item['PK'],item['SK'])).fetchone()
        if current and current[0]==encoded:
            return 'existentes_identicos'
        raise ValueError(f'Colisión con contenido diferente: {table}/{item["PK"]}/{item["SK"]}')

    def pages(self, table: str, tenant: str, page_size: int=137):
        last=''
        while True:
            page=self.db.execute('SELECT sk,cuerpo FROM items WHERE tabla=? AND pk=? AND sk>? ORDER BY sk LIMIT ?', (table,f'TENANT#{tenant}',last,page_size)).fetchall()
            if not page:
                break
            yield [json.loads(row[1]) for row in page]
            last=page[-1][0]


class AwsStore:
    def __init__(self, region: str, account: str, stage: str) -> None:
        import boto3
        self.session=boto3.Session(region_name=region)
        actual=self.session.client('sts').get_caller_identity()['Account']
        if actual!=account: raise ValueError('Cuenta STS distinta de la confirmada')
        self.resource=self.session.resource('dynamodb')
        self.names={s:f'trazora-{s}-{stage}' for s in SERVICES}
        for name in self.names.values():
            meta=self.resource.meta.client.describe_table(TableName=name)['Table']
            attributes={x['AttributeName']:x['AttributeType'] for x in meta['AttributeDefinitions']}
            if (meta['TableName'] != name or meta['TableStatus']!='ACTIVE' or meta['KeySchema']!=[{'AttributeName':'PK','KeyType':'HASH'},{'AttributeName':'SK','KeyType':'RANGE'}] or attributes.get('PK')!='S' or attributes.get('SK')!='S'):
                raise ValueError(f'Tabla incompatible: {name}')
            print(json.dumps({'tabla':name,'modo':meta.get('BillingModeSummary'),'streams':meta.get('StreamSpecification'),'indices':meta.get('GlobalSecondaryIndexes',[])},default=str))

    def insert(self, table: str, item: dict) -> str:
        from botocore.exceptions import ClientError
        target=self.resource.Table(self.names[table])
        try:
            target.put_item(Item=item,ConditionExpression='attribute_not_exists(PK)')
            return 'escritos'
        except ClientError as exc:
            if exc.response['Error']['Code']!='ConditionalCheckFailedException': raise
            current=target.get_item(Key={'PK':item['PK'],'SK':item['SK']},ConsistentRead=True).get('Item')
            if current==item: return 'existentes_identicos'
            raise ValueError(f'Colisión con contenido diferente: {table}/{item["PK"]}/{item["SK"]}') from exc

    def pages(self, table: str, tenant: str):
        from boto3.dynamodb.conditions import Key
        target=self.resource.Table(self.names[table]);args={'KeyConditionExpression':Key('PK').eq(f'TENANT#{tenant}'),'ConsistentRead':True}
        cursors=set()
        while True:
            page=target.query(**args)
            yield page.get('Items',[])
            if not page.get('LastEvaluatedKey'): break
            cursor=canonical(page['LastEvaluatedKey'])
            if cursor in cursors: raise ValueError('Cursor de DynamoDB repetido')
            cursors.add(cursor)
            args['ExclusiveStartKey']=page['LastEvaluatedKey']


def verify(folder: Path, store: LocalStore | AwsStore) -> dict:
    expected: dict[str,dict[tuple[str,str],str]]={s:{} for s in SERVICES}
    for table,item in items(folder): expected[table][(item['PK'],item['SK'])]=canonical(item)
    seen=Counter(); seen_types=Counter(); observed={s:set() for s in SERVICES}; divergent=[];unexpected=Counter();pages=0
    for table in SERVICES:
        for tenant in TENANTS:
            for page in store.pages(table,tenant):
                pages+=1
                for item in page:
                    key=(item['PK'],item['SK'])
                    if item['PK'] != f'TENANT#{tenant}' or key in observed[table]: raise ValueError('Lectura con tenant incorrecto o clave repetida')
                    observed[table].add(key)
                    exp=expected[table].get(key)
                    if exp is None:
                        unexpected[table]+=1
                    elif canonical(item)==exp:
                        seen[table]+=1
                        seen_types[item['entity_type']]+=1
                    else:
                        divergent.append([table,*key])
    missing={s:len(expected[s])-seen[s]-sum(x[0]==s for x in divergent) for s in SERVICES}
    return {'ok':not any(missing.values()) and not divergent,'verificados':dict(seen),'verificados_por_entidad':dict(seen_types),'faltantes':missing,'divergentes':divergent[:20],'total_divergentes':len(divergent),'ajenos':dict(unexpected),'paginas':pages}


def load(folder: Path, store: LocalStore | AwsStore, stop_after: int=0, max_writes_per_second: float=0) -> dict:
    counts=Counter(); per_type=Counter();counts['generados']=sum(1 for _ in items(folder))
    next_write = time.monotonic()
    for table,item in items(folder):
        if max_writes_per_second:
            delay = next_write - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            next_write = time.monotonic() + 1 / max_writes_per_second
        if stop_after and counts['intentados']>=stop_after:
            return {'estado':'interrumpido',**counts,'por_entidad':dict(per_type)}
        counts['intentados']+=1
        per_type[f"{item['entity_type']}/intentados"]+=1
        try:
            result=store.insert(table,item)
        except Exception:
            counts['rechazados']+=1
            per_type[f"{item['entity_type']}/rechazados"]+=1
            print(json.dumps({'estado':'error',**counts},ensure_ascii=False))
            raise
        counts[result]+=1
        per_type[f"{item['entity_type']}/{result}"]+=1
    report=verify(folder,store)
    return {'estado':'verificado' if report['ok'] else 'incompleto',**counts,'por_entidad':dict(per_type),'lectura':report}


def main() -> None:
    p=argparse.ArgumentParser(description='Simulación y carga condicional verificable')
    p.add_argument('--input',type=Path,required=True);p.add_argument('--target',type=int,default=37000)
    p.add_argument('--simular',type=Path,help='Ruta de base SQLite local');p.add_argument('--verificar',action='store_true')
    p.add_argument('--interrumpir-tras',type=int,default=0)
    p.add_argument('--inspeccionar-aws',action='store_true');p.add_argument('--apply',action='store_true')
    p.add_argument('--stage');p.add_argument('--region');p.add_argument('--cuenta');p.add_argument('--revision-permisos-colisiones-streams-cuotas-costos',action='store_true')
    p.add_argument('--confirmar-carga',default='');p.add_argument('--max-escrituras-seg',type=float,default=5)
    a=p.parse_args()
    if not 0 < a.max_escrituras_seg <= 50: p.error('El límite debe estar entre 0 y 50 operaciones por segundo')
    if a.interrumpir_tras < 0: p.error('La interrupción debe ser no negativa')
    report=validate(a.input,a.target);print(json.dumps({'validacion_local':report['business_records']}))
    if a.simular:
        if a.apply or a.inspeccionar_aws: p.error('Seleccione simulación o AWS')
        store=LocalStore(a.simular)
        result=verify(a.input,store) if a.verificar else load(a.input,store,a.interrumpir_tras)
    elif a.inspeccionar_aws or a.apply:
        if not all((a.stage,a.region,a.cuenta)):p.error('Requiere --stage, --region y --cuenta')
        if not re.fullmatch(r'[a-z0-9-]{1,30}',a.stage) or not re.fullmatch(r'\d{12}',a.cuenta):p.error('Etapa o cuenta inválida')
        store=AwsStore(a.region,a.cuenta,a.stage)
        before=verify(a.input,store);print(json.dumps({'estado_previo':before},ensure_ascii=False))
        if a.apply:
            if a.stage != 'dev':p.error('La escritura solo se permite en etapa dev')
            if not a.revision_permisos_colisiones_streams_cuotas_costos or a.confirmar_carga!='ESCRIBIR':p.error('Faltan las confirmaciones de revisión y escritura')
            if before['total_divergentes']:p.error('Se detectaron colisiones con contenido diferente')
            result=load(a.input,store,max_writes_per_second=a.max_escrituras_seg)
        else: result={'estado':'inspeccion_sin_escrituras','lectura':before}
    else:
        result={'estado':'inspeccion_local','negocio_generado':report['business_records'],'auxiliares_generados':report['auxiliary_records']}
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    if result.get('estado') in ('incompleto','interrumpido') or (a.verificar and not result.get('ok',False)):
        raise SystemExit(2)

if __name__=='__main__': main()
