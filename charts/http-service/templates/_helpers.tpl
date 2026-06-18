{{- define "http-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "http-service.fullname" -}}
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

{{- define "http-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "http-service.labels" -}}
helm.sh/chart: {{ include "http-service.chart" . | quote }}
{{ include "http-service.baseSelectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "http-service.baseSelectorLabels" -}}
app.kubernetes.io/name: {{ include "http-service.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "http-service.selectorLabels" -}}
{{ include "http-service.baseSelectorLabels" . }}
app.kubernetes.io/component: {{ .Values.component | quote }}
{{- end -}}

{{- define "http-service.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "http-service.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "http-service.externalSecretsServiceAccountName" -}}
{{- default (printf "%s-external-secrets" (include "http-service.fullname" .)) .Values.externalSecrets.serviceAccount.name -}}
{{- end -}}

{{- define "http-service.secretStoreName" -}}
{{- printf "%s-openbao" (include "http-service.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
