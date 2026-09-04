pragma solidity ^0.8.0;
contract InternalFunctionsFixture { function twice(uint256 value) external pure returns (uint256) { return _twice(value); } function _twice(uint256 value) internal pure returns (uint256) { return value * 2; } }
