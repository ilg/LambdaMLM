# LambdaMLM

A mailing list manager (MLM or email discussion list software) that runs on AWS Lambda (with help from SES and S3).

***LambdaMLM is not production-ready.  Use LambdaMLM at your own risk.***

Planned enhancements, bugs, and known limitations are tracked in [GitHub Issues](https://github.com/ilg/LambdaMLM/issues).

Setup requires familiarity with AWS—in particular, having credentials already set up locally and having familiarity with SES, IAM, and Lambda will help.  A rough outline of how to set up LambdaMLM is [here](docs/setup.md).

## [Documentation](docs/)

- [Commands](docs/commands.md)
- [List Configuration](docs/list%20configuration.md)
- [Setup](docs/setup.md)
- [Technical](docs/technical.md)

## Tests

The test suite runs on Python 2.7 in Docker (see the [modernization plan](docs/modernization-plan.md)):

```sh
scripts/test-py2
```

Arguments are passed through to `pytest`.  Tests never contact AWS: S3 and SES are replaced with in-memory fakes, and any real AWS request fails the test.

## License

[MIT License](LICENSE)

## Author

[Isaac Greenspan](https://github.com/ilg), with some time contributed by [Vokal](http://vokal.io).
