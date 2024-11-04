# Librerias
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.operators.dummy import DummyOperator
from datetime import timedelta
from airflow.utils.dates import days_ago
from google.cloud import bigquery

# Funciones
from functions.v2_registrar_archivo import obtener_archivos_nuevos, registrar_archivos_en_bq
from functions.tabla_temporal import crear_tabla_temporal, cargar_json_a_bigquery

######################################################################################
# PARÁMETROS
######################################################################################

nameDAG_base       = 'ETL_Storage_to_BQ'
project_id         = 'neon-gist-439401-k8'
dataset            = '1'
owner              = 'Mauricio Arce'
GBQ_CONNECTION_ID  = 'bigquery_default'
bucket_name        = 'datos-crudos'
prefix             = 'g_sitios/'
temp_table_general = 'data_cruda'

default_args = {
    'owner': owner,
    'start_date': days_ago(1),
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

# Tabla temporal de la metadata cruda que se va a desanidar y procesar.
temp_table_general_schema = [
    bigquery.SchemaField("name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("address", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("gmap_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("latitude", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("longitude", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("category", "STRING", mode="REPEATED"),
    bigquery.SchemaField("avg_rating", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("num_of_reviews", "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("price", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("hours", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("day", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("time", "STRING", mode="REQUIRED"),
    ]),
    bigquery.SchemaField("MISC", "RECORD", mode="NULLABLE", fields=[
        bigquery.SchemaField("Service options", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Health & safety", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Accessibility", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Planning", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Payments", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Highlights", "STRING", mode="REPEATED"),  # Campo agregado
    ]),
    bigquery.SchemaField("state", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("relative_results", "STRING", mode="REPEATED"),
    bigquery.SchemaField("url", "STRING", mode="NULLABLE"),
]


#######################################################################################
# DEFINICIÓN DEL DAG 
#######################################################################################

with DAG(
    dag_id=nameDAG_base,
    default_args=default_args,
    schedule_interval=None,
    catchup=False
) as dag:

    inicio = DummyOperator(task_id='inicio')

    # Tarea 1: Registrar archivos en una tabla que controlara cuales ya fueron procesados y cuales no.
    registrar_archivos = PythonOperator(
        task_id='registrar_archivos_procesados',
        python_callable=obtener_archivos_nuevos,
        op_kwargs={
            'bucket_name': bucket_name,
            'prefix': prefix,
            'project_id': project_id,
            'dataset': dataset
        },
    )

    # Tarea 2: Crear la tabla temporal en BigQuery de todo el Json.
    crear_tabla_temp = PythonOperator(
        task_id='crear_tabla_temporal',
        python_callable=crear_tabla_temporal,
        op_kwargs={
            'project_id': project_id,
            'dataset': dataset,
            'temp_table': temp_table_general,
            'schema': temp_table_general_schema 
        },
    )

   # Tarea 3: Cargar los archivos JSON en la tabla temporal
    # Tarea 3: Cargar los archivos JSON en la tabla temporal
    cargar_json = GCSToBigQueryOperator(
        task_id='cargar_json',
        bucket=bucket_name,
        source_objects=["g_sitios/*.json"],  # Usa un patrón para cargar todos los archivos .json en la carpeta g_sitios
        destination_project_dataset_table=f'{project_id}.{dataset}.{temp_table_general}',  # Especifica la tabla temporal
        source_format='NEWLINE_DELIMITED_JSON',
        create_disposition='CREATE_IF_NEEDED',
        write_disposition='WRITE_APPEND',
    )
    
    # Tarea 4: Registrar el nombre de los archivos cargados en BigQuery, para control.
    registrar_archivo_en_bq = PythonOperator(
        task_id='registrar_archivo_en_bq',
        python_callable=registrar_archivos_en_bq,
        op_kwargs={
            'project_id': project_id,
            'dataset': dataset,
            'archivo_nuevo': "{{ task_instance.xcom_pull(task_ids='registrar_archivos_procesados') }}",
        }
    )

    fin = DummyOperator(task_id='fin')

    # Estructura del flujo de tareas
    inicio >> registrar_archivos >> crear_tabla_temp >> cargar_json >>  registrar_archivo_en_bq >> fin

    