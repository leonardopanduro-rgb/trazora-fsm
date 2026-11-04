from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
import uuid
from generar_datos import AUX, PHONE_FORMATS, SERVICES, SPECIALTIES, TENANTS, quota

ENTITIES={'usuarios':'USUARIO','clientes':'CLIENTE','tecnicos':'TECNICO','ordenes':'ORDEN','agenda':'VISITA','partes':'PARTE','jornadas':'JORNADA','bloques':'BLOQUE','controles':'CONTROL_ORDEN','marcadores':'VISITA_PARTE'}
TABLE={'jornadas':'tecnicos','bloques':'agenda','controles':'agenda','marcadores':'partes'}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def parse(value: str) -> datetime:
    require(isinstance(value,str) and value.endswith('Z'), f'Fecha UTC inválida: {value}')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def rows(path: Path):
    with path.open(encoding='utf-8') as source:
        for number,line in enumerate(source,1):
            try:
                obj=json.loads(line)
                require(isinstance(obj,dict),'se esperaba objeto')
                yield obj
            except (ValueError,TypeError) as exc:
                raise ValueError(f'{path.name}:{number}: {exc}') from exc


def validate_email(value: str, used: set[str]) -> None:
    pattern = r"[a-z0-9]+(?:[._][a-z0-9]+)*@[a-z0-9]+\.invalid"
    require(isinstance(value, str) and len(value) <= 254 and len(value.split('@')[0]) <= 64 and re.fullmatch(pattern, value) is not None, 'Correo sintético inválido')
    require(re.search(r'\d{5}', value.split('@')[0]) is None, 'Secuencia numérica excesiva en correo')
    require(value not in used, 'Correo duplicado')
    used.add(value)


def validate(folder: Path, target: int=37000) -> dict:
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    require(manifest['target']==target,'Objetivo del manifiesto incorrecto')
    counts=defaultdict(Counter); types=defaultdict(Counter); keys=defaultdict(set); ids=defaultdict(set)
    data={name:{} for name in ENTITIES}; all_rows={name:[] for name in ENTITIES}
    for service,entity in ENTITIES.items():
        path=folder/f'{service}.jsonl'
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest==manifest['files'][path.name],f'SHA256 inválido: {path.name}')
        for row in rows(path):
            pk=row.get('PK');sk=row.get('SK');tenant=pk.removeprefix('TENANT#') if isinstance(pk,str) else ''
            require(tenant in TENANTS and pk==f'TENANT#{tenant}','PK o tenant inválido')
            require(row.get('tenant_id',tenant)==tenant,'Tenant distinto de PK')
            require(row.get('entity_type')==entity, f'Entidad inválida en {service}')
            key=(pk,sk); table=TABLE.get(service,service)
            require(key not in keys[table],f'Clave duplicada {table}/{key}')
            keys[table].add(key); counts[service][tenant]+=1;types[service][entity]+=1
            field={'USUARIO':'usuario_id','CLIENTE':'cliente_id','TECNICO':'tecnico_id','ORDEN':'orden_id','VISITA':'visita_id','PARTE':'parte_id'}.get(entity)
            if field:
                val=row[field]
                try: valid=str(uuid.UUID(val))==val
                except (ValueError,TypeError,AttributeError): valid=False
                require(valid,f'UUID inválido {field}')
                require(val not in ids[entity],f'ID duplicado {entity}')
                ids[entity].add(val); require(sk==f'{entity}#{val}',f'SK no coincide {entity}')
                data[service][(tenant,val)]=row
            else:
                all_rows[service].append((tenant,row))
    for service in SERVICES:
        require(dict(counts[service])==quota(target),f'Conteo incorrecto {service}: {counts[service]}')
    for service in ('controles','marcadores'):
        require(dict(counts[service])==quota(target),f'Auxiliares incorrectos {service}')
    emails: set[str] = set()
    for (tenant,_),r in data['usuarios'].items():
        require(r['estado']=='INACTIVO' and r['rol'] in ('ADMIN','COORDINADOR','TECNICO') and 'password_hash' not in r,'Usuario inválido')
        validate_email(r['email_normalizado'], emails)
    company_domains: set[str] = set()
    for (tenant,_),r in data['clientes'].items():
        require(r['activo'] is True and 1<=len(r['nombre'])<=160 and any(re.fullmatch(re.escape(fmt).replace(re.escape('{tail:03d}'), r'[0-9]{3}'), r['telefono']) is not None for fmt in PHONE_FORMATS.values()),'Cliente inválido')
        validate_email(r['correo'], emails)
        if r['nombre'].endswith(('S.A.C.', 'S.R.L.', 'E.I.R.L.')):
            domain = r['correo'].split('@')[1]
            require(domain not in company_domains, 'Dominio empresarial repetido')
            company_domains.add(domain)
    for (tenant,_),r in data['tecnicos'].items():
        specs=r['especialidades'];require(type(r['activo']) is bool and 3<=len(r['nombre'])<=120 and 1<=len(specs)<=3 and len(set(specs))==len(specs) and set(specs)<=set(SPECIALTIES),'Técnico inválido')
    jornadas={}
    for tenant,r in all_rows['jornadas']:
        key=(tenant,r['tecnico_id'],r['fecha']); require((tenant,r['tecnico_id']) in data['tecnicos'],'Jornada huérfana')
        require(data['tecnicos'][(tenant,r['tecnico_id'])]['activo'] is True,'Jornada de técnico inactivo')
        require(r['SK']==f"JORNADA#{r['tecnico_id']}#{r['fecha']}" and r['zona_horaria']=='America/Lima','Jornada inválida')
        require(key not in jornadas,'Jornada duplicada');jornadas[key]=r
    for (tenant,oid),r in data['ordenes'].items():
        require((tenant,r['cliente_id']) in data['clientes'] and (tenant,r['creada_por']) in data['usuarios'],'Orden huérfana o cruzada')
        creator=data['usuarios'][(tenant,r['creada_por'])]
        require(creator['rol'] in ('ADMIN','COORDINADOR') and parse(creator['creado_en'])<=parse(r['creada_en']), 'Creador de orden incompatible')
        require(parse(data['clientes'][(tenant,r['cliente_id'])]['creado_en'])<=parse(r['creada_en'])<=datetime.now(timezone.utc),'Fecha de orden inválida')
        require(r['estado']=='ABIERTA' and r['tipo_servicio'] in SPECIALTIES and r['prioridad'] in ('BAJA','MEDIA','ALTA') and 10<=len(r['descripcion'])<=500,'Orden inválida')
    expected_blocks=set(); expected_controls={}; used_jornadas=set(); schedules=defaultdict(list)
    for (tenant,vid),v in data['agenda'].items():
        order=data['ordenes'].get((tenant,v['orden_id']));tech=data['tecnicos'].get((tenant,v['tecnico_id']))
        require(order is not None and tech is not None,'Visita huérfana o cruzada')
        require(tech['activo'] is True,'Visita de técnico inactivo')
        require(v['estado']=='PROGRAMADA' and order['tipo_servicio'] in tech['especialidades'],'Estado o especialidad inválida')
        a,b=parse(v['inicio']),parse(v['fin']); created=parse(v['creada_en']); local_a=a-timedelta(hours=5);local_b=b-timedelta(hours=5)
        require(a.second==0 and b.second==0 and a.microsecond==0 and b.microsecond==0 and a.minute in (0,30) and b.minute in (0,30) and 30<=(b-a).total_seconds()/60<=240 and (b-a).total_seconds()%1800==0,'Duración inválida')
        require(parse(order['creada_en'])<=created<=datetime.now(timezone.utc) and parse(tech['creado_en'])<=created<a<b,'Cronología inválida')
        day=local_a.date().isoformat(); j=jornadas.get((tenant,v['tecnico_id'],day));require(j is not None and local_a.date()==local_b.date(),'Visita sin jornada')
        used_jornadas.add((tenant,v['tecnico_id'],day))
        require(any(x['inicio']<=local_a.strftime('%H:%M') and local_b.strftime('%H:%M')<=x['fin'] for x in j['intervalos']),'Visita fuera de jornada')
        schedules[(tenant,v['tecnico_id'])].append((a,b)); expected_controls[(tenant,v['orden_id'])]=expected_controls.get((tenant,v['orden_id']),0)+1
        while a<b:
            expected_blocks.add((tenant,f"BLOQUE#{v['tecnico_id']}#{a.isoformat(timespec='seconds').replace('+00:00','Z')}",vid));a+=timedelta(minutes=30)
    require(set(jornadas)==used_jornadas,'Jornadas no utilizadas o ausentes')
    active_technicians={key for key,tech in data['tecnicos'].items() if tech['activo'] is True}
    assigned_technicians={(tenant,visit['tecnico_id']) for (tenant,_),visit in data['agenda'].items()}
    require(active_technicians==assigned_technicians,'Técnicos activos y asignados no coinciden')
    for slots in schedules.values():
        slots.sort();require(all(a[1]<=b[0] for a,b in zip(slots,slots[1:])), 'Visitas superpuestas')
    for t,r in all_rows['bloques']:
        require(r['tecnico_id']==data['agenda'].get((t,r['visita_id']),{}).get('tecnico_id'),'Bloque con técnico incorrecto')
    blocks={(t,r['SK'],r['visita_id']) for t,r in all_rows['bloques']}
    require(blocks==expected_blocks and len(blocks)==len(all_rows['bloques']),'Bloques ausentes o sobrantes')
    controls={(t,r['orden_id']):r for t,r in all_rows['controles']}
    require(set(controls)==set(expected_controls),'Controles huérfanos o ausentes')
    for key,r in controls.items():
        require(r['SK']==f'CONTROL_ORDEN#{key[1]}' and r['acepta_programaciones'] is True and r['visitas_activas']==expected_controls[key],'Control inválido')
    markers={(t,r['visita_id']):r for t,r in all_rows['marcadores']}
    require(set(markers)==set(data['agenda']),'Marcadores huérfanos o ausentes')
    referenced=set()
    for key,mark in markers.items():
        t,vid=key; part=data['partes'].get((t,mark['parte_id'])); visit=data['agenda'][key]
        require(mark['SK']==f'VISITA_PARTE#{vid}' and part is not None,'Marcador inválido')
        require(part['visita_id']==vid and part['orden_id']==visit['orden_id'] and part['estado']=='BORRADOR' and part['resultado']=='PENDIENTE' and part['diagnostico']=='' and part['tareas']==[] and part['version']==1,'Parte incompatible')
        require((t,part['creado_por']) in data['usuarios'] and data['usuarios'][(t,part['creado_por'])]['rol'] in ('ADMIN','COORDINADOR') and parse(data['usuarios'][(t,part['creado_por'])]['creado_en'])<=parse(part['creado_en']) and parse(visit['creada_en'])<=parse(part['creado_en'])<=parse(part['actualizado_en'])<=datetime.now(timezone.utc) and parse(part['actualizado_en'])<parse(visit['inicio']),'Cronología de parte inválida')
        referenced.add((t,part['parte_id']))
    require(referenced==set(data['partes']),'Parte huérfano')
    return {'ok':True,'target':target,'business_records':sum(sum(counts[s].values()) for s in SERVICES),'auxiliary_records':sum(sum(counts[s].values()) for s in AUX),'counts':{s:dict(counts[s]) for s in ENTITIES},'types':{s:dict(types[s]) for s in ENTITIES}}


def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path);p.add_argument('--target',type=int,default=37000);a=p.parse_args()
    print(json.dumps(validate(a.input,a.target),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
