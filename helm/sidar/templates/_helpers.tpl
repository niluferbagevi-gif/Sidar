{{- define "sidar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sidar.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "sidar.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "sidar.otelEndpoint" -}}
{{- if .Values.apm.enabled -}}
{{- printf "http://%s-otel-collector:%v" (include "sidar.fullname" .) (.Values.apm.collector.service.grpcPort | default 4317) -}}
{{- else -}}
{{- default "http://jaeger:4317" .Values.env.OTEL_EXPORTER_ENDPOINT -}}
{{- end -}}
{{- end -}}
