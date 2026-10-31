// CloudFront viewer-request function (D23): HTTP basic auth for the whole demo, and SPA routing
// for the React app. API and DICOMweb paths are never rewritten, so an API 404 ("no data")
// reaches the browser unchanged (D17).
function handler(event) {
  var request = event.request;
  var auth = request.headers.authorization;
  if (!auth || auth.value !== 'Basic ${basic_auth}') {
    return {
      statusCode: 401,
      statusDescription: 'Unauthorized',
      headers: { 'www-authenticate': { value: 'Basic realm="CochleaHub demo"' } },
    };
  }
  var uri = request.uri;
  var routed = uri.indexOf('/api/') === 0 || uri.indexOf('/dicom-web/') === 0;
  // client-side routes (/specimens/zeta, /assistant) have no file extension
  if (!routed && uri.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
