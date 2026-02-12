"""
Script de diagnóstico para verificar atualização de progresso.

Por padrão, este script roda em modo somente leitura.
Para escrever no Firestore, use --write e confirme explicitamente.
"""
import argparse
import os
import sys
from google.cloud import firestore


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de projeto no Firestore")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT"), help="GCP project ID")
    parser.add_argument("--project-id", dest="target_project_id", help="ID do projeto de photogrammetry")
    parser.add_argument("--write", action="store_true", help="Permite atualização de teste no Firestore")
    args = parser.parse_args()

    gcp_project = args.project
    if not gcp_project:
        print("Defina --project ou GCP_PROJECT para continuar.")
        return 1

    test_project_id = (args.target_project_id or input("Digite o project_id para testar: ").strip())
    if not test_project_id:
        print("Project ID é obrigatório!")
        return 1

    client = firestore.Client(project=gcp_project)
    projects_collection = client.collection("projects")
    doc = projects_collection.document(test_project_id).get()

    if not doc.exists:
        print(f"Projeto {test_project_id} não encontrado no Firestore.")
        return 1

    project_data = doc.to_dict()
    print(f"\nProjeto encontrado: {project_data.get('name', 'Sem nome')}")
    print(f"Status: {project_data.get('status')}")
    print(f"Progresso: {project_data.get('progress', 0)}%")
    print(f"Última atualização: {project_data.get('updated_at', 'N/A')}")
    print(f"Criado em: {project_data.get('created_at', 'N/A')}")
    print(f"Arquivos: {project_data.get('files_count', len(project_data.get('files', [])))}")

    batch_job = project_data.get('batch_job')
    if batch_job:
        print("\nBatch Job:")
        print(f"Job ID: {batch_job.get('job_id', 'N/A')}")
        print(f"Status: {batch_job.get('status', 'N/A')}")
        print(f"Criado em: {batch_job.get('created_at', 'N/A')}")

    if not args.write:
        print("\nModo somente leitura ativo. Nenhuma escrita foi realizada.")
        return 0

    confirmation = input(
        f"CONFIRME a escrita em '{gcp_project}' digitando exatamente WRITE: "
    ).strip()
    if confirmation != "WRITE":
        print("Escrita cancelada.")
        return 1

    print("\nTestando atualização de progresso...")
    try:
        test_updates = {
            "progress": 50,
            "updated_at": "2026-02-09T16:00:00Z"
        }
        projects_collection.document(test_project_id).update(test_updates)
        print("Atualização de teste bem-sucedida.")
        updated_doc = projects_collection.document(test_project_id).get()
        updated_data = updated_doc.to_dict()
        print(f"Novo progresso: {updated_data.get('progress', 0)}%")
        return 0
    except Exception as exc:
        print(f"Erro ao atualizar: {exc}")
        print("Possíveis causas:")
        print("1. Permissões IAM insuficientes")
        print("2. Projeto Firestore não configurado corretamente")
        print("3. Credenciais não configuradas")
        return 1


if __name__ == "__main__":
    sys.exit(main())
