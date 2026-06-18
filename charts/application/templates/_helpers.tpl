{{- define "application.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "application.fullname" -}}
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

{{- define "application.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "application.labels" -}}
helm.sh/chart: {{ include "application.chart" . | quote }}
{{ include "application.baseSelectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "application.baseSelectorLabels" -}}
app.kubernetes.io/name: {{ include "application.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "application.selectorLabels" -}}
{{ include "application.baseSelectorLabels" . }}
app.kubernetes.io/component: {{ .Values.component | quote }}
{{- end -}}

{{- define "application.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "application.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "application.externalSecretsServiceAccountName" -}}
{{- default (printf "%s-external-secrets" (include "application.fullname" .)) .Values.externalSecrets.serviceAccount.name -}}
{{- end -}}

{{- define "application.secretStoreName" -}}
{{- printf "%s-openbao" (include "application.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
