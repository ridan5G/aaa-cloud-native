{{/*
Expand the name of the chart.
*/}}
{{- define "aaa-database.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "aaa-database.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label value — used in helm.sh/chart label.
*/}}
{{- define "aaa-database.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
CloudNativePG Cluster resource name.
Truncated to 50 chars so that CNPG can append "-<instance-n>" and remain under 63.
Override with clusterNameOverride for dev environments (e.g. "aaa-postgres").
*/}}
{{- define "aaa-database.clusterName" -}}
{{- if .Values.clusterNameOverride }}
{{- .Values.clusterNameOverride | trunc 50 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-postgres" (include "aaa-database.fullname" .) | trunc 50 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
PgBouncer RW Pooler resource name (routes to primary).
*/}}
{{- define "aaa-database.poolerRWName" -}}
{{- printf "%s-pooler-rw" (include "aaa-database.clusterName" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
PgBouncer RO Pooler resource name (routes to sync standbys).
*/}}
{{- define "aaa-database.poolerROName" -}}
{{- printf "%s-pooler-ro" (include "aaa-database.clusterName" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Name of the Secret that holds app credentials.
If existingAppSecret is set, that name takes priority; otherwise use appCredentialsSecretName.
*/}}
{{- define "aaa-database.appSecretName" -}}
{{- if .Values.postgresql.existingAppSecret }}
{{- .Values.postgresql.existingAppSecret }}
{{- else }}
{{- .Values.postgresql.appCredentialsSecretName }}
{{- end }}
{{- end }}

{{/*
Common labels applied to all resources in this chart.
*/}}
{{- define "aaa-database.labels" -}}
helm.sh/chart: {{ include "aaa-database.chart" . }}
{{ include "aaa-database.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: database
{{- end }}

{{/*
Selector labels — used in matchLabels and pod selectors.
*/}}
{{- define "aaa-database.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aaa-database.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
