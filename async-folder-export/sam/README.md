# SAM — export revision pipeline

Deploys **ExportRevisionQueue** (+ DLQ), **SNS → SQS subscription** with message-attribute filter, **deduplication table**, **ExportUpdateHandler**, **ExportRevisionLogger**, and **CloudWatch alarms**.

## Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Parameters: jobs table **stream ARN**, existing **`TcFileServiceTopic` ARN**, Monolith **revision log URL**

## Build and deploy

From this directory:

```bash
sam build --template-file template.yaml
sam deploy --guided \
  --parameter-overrides \
    JobsTableStreamArn=arn:aws:dynamodb:region:account:table/.../stream/... \
    ExistingSnsTopicArn=arn:aws:sns:region:account:TcFileServiceTopic \
    MonolithRevisionLogUrl=https://monolith.example/api/logRevisionAsync \
    RevisionLogAuthHeader='Bearer ...'
```

`RevisionLogAuthHeader` can be omitted or set empty if the endpoint does not require it.

## Alarms (observability)

| Alarm | Signal |
|-------|--------|
| `*-revision-queue-old-message` | `ApproximateAgeOfOldestMessage` on **ExportRevisionQueue** |
| `*-revision-dlq-depth` | Messages on **revision DLQ** |
| `*-export-update-handler-errors` | Lambda **Errors** (stream → SNS) |
| `*-export-revision-logger-errors` | Lambda **Errors** (SQS → Monolith) |
| `*-sns-notifications-failed` | **NumberOfNotificationsFailed** on the topic |

Wire `AlarmActions` to your SNS/PagerDuty topic in a wrapper stack or manually after first deploy.

## Notes

- Subscription uses **MessageAttributes** filter: `eventType=connect.export.completed`, `jobType=EXPORT`. Add `connect.export.failed` in `template.yaml` if revision logging must record failures.
- Handlers live under [../lambda/](../lambda/).
