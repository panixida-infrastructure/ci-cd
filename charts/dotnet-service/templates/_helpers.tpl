{{- define "dotnet-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dotnet-service.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "dotnet-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dotnet-service.labels" -}}
helm.sh/chart: {{ include "dotnet-service.chart" . | quote }}
{{ include "dotnet-service.baseSelectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "dotnet-service.baseSelectorLabels" -}}
app.kubernetes.io/name: {{ include "dotnet-service.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "dotnet-service.selectorLabels" -}}
{{ include "dotnet-service.baseSelectorLabels" . }}
app.kubernetes.io/component: {{ .Values.component | quote }}
{{- end -}}

{{- define "dotnet-service.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "dotnet-service.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "dotnet-service.externalSecretsServiceAccountName" -}}
{{- default (printf "%s-external-secrets" (include "dotnet-service.fullname" .)) .Values.externalSecrets.serviceAccount.name -}}
{{- end -}}

{{- define "dotnet-service.secretStoreName" -}}
{{- printf "%s-openbao" (include "dotnet-service.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
